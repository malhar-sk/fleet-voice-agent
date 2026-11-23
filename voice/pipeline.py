"""Pipecat pipeline for one browser WebRTC session.

  SmallWebRTCTransport.input()  (mic, 16 kHz)
    -> VADProcessor(SileroVADAnalyzer)                 speech start / stop
    -> FleetTurnProcessor                               buffers the utterance, then runs VoiceEngine:
                                                        faster-whisper -> agent (LLM + tools) -> Piper
    -> SmallWebRTCTransport.output() (speaker)

The turn processor is half-duplex: speech that starts while the bot is thinking is ignored (no barge-in).
Transcript, tool calls and timings are sent to the page over the WebRTC data channel.
"""
from __future__ import annotations

import asyncio
import collections
import time

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams

from voice.engine import MIN_SPEECH_S, VoiceEngine
from voice.stt import pcm16_to_float

VAD_STOP_SECS = 0.6
PREROLL_S = 0.5      # VAD fires after start_secs of speech; keep the audio just before it


class FleetTurnProcessor(FrameProcessor):
    def __init__(self, engine: VoiceEngine, **kwargs):
        super().__init__(**kwargs)
        self.engine = engine
        self._speaking = False
        self._busy = False
        self._buf = bytearray()
        self._pre: collections.deque[bytes] = collections.deque()
        self._pre_bytes = 0
        self._sr = 16000
        self._tasks: set[asyncio.Task] = set()

    async def _send(self, msg: dict):
        await self.push_frame(OutputTransportMessageUrgentFrame(message=msg))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self._sr = frame.sample_rate
            if self._speaking:
                self._buf.extend(frame.audio)
            else:
                self._pre.append(frame.audio)
                self._pre_bytes += len(frame.audio)
                while self._pre_bytes > PREROLL_S * self._sr * 2 and self._pre:
                    self._pre_bytes -= len(self._pre.popleft())
            return
        if isinstance(frame, VADUserStartedSpeakingFrame):
            if not self._busy:
                self._speaking = True
                self._buf = bytearray(b"".join(self._pre))
                await self._send({"type": "listening"})
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            if self._speaking:
                self._speaking = False
                audio = bytes(self._buf)
                self._buf = bytearray()
                if len(audio) / 2 / self._sr >= MIN_SPEECH_S:
                    t = asyncio.create_task(self._run_turn(audio, self._sr, time.perf_counter()))
                    self._tasks.add(t)
                    t.add_done_callback(self._tasks.discard)
        await self.push_frame(frame, direction)

    async def _run_turn(self, pcm: bytes, sr: int, t_vad_stop: float):
        self._busy = True
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        await self._send({"type": "thinking"})

        def on_chunk(c):
            loop.call_soon_threadsafe(q.put_nowait, c)

        fut = loop.run_in_executor(None, self.engine.turn_stream, pcm16_to_float(pcm), sr, on_chunk)
        first = True
        try:
            while True:
                getter = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({getter, fut}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    c = getter.result()
                    if first:
                        first = False
                        logger.info(f"first reply audio {1000 * (time.perf_counter() - t_vad_stop):.0f} ms after VAD stop")
                    await self.push_frame(OutputAudioRawFrame(audio=c.pcm, sample_rate=c.sample_rate, num_channels=1))
                    continue
                getter.cancel()
                while not q.empty():
                    c = q.get_nowait()
                    await self.push_frame(OutputAudioRawFrame(audio=c.pcm, sample_rate=c.sample_rate, num_channels=1))
                break
            result = fut.result()
            await self._send({"type": "turn", "transcript": result.transcript, "lang": result.lang,
                              "answer": result.answer, "tool_calls": [
                                  {"tool": t["tool"], "args": t["args"]} for t in result.agent.get("tool_calls", [])],
                              "backend": result.agent.get("backend"), "timings_ms": result.timings_ms})
        except Exception as e:  # never kill the session on one bad turn
            logger.exception("turn failed")
            await self._send({"type": "error", "error": str(e)[:300]})
        finally:
            self._busy = False


async def run_bot(webrtc_connection, engine: VoiceEngine):
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True,
                               audio_in_sample_rate=16000, audio_out_sample_rate=22050),
    )
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(sample_rate=16000, params=VADParams(stop_secs=VAD_STOP_SECS)))
    pipeline = Pipeline([transport.input(), vad, FleetTurnProcessor(engine), transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=22050))

    @transport.event_handler("on_client_disconnected")
    async def _gone(_t, _c):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
