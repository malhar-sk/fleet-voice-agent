FROM python:3.11-slim
WORKDIR /app
COPY fleet_sim /app/fleet_sim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "fleet_sim.sim"]
