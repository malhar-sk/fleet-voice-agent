/** Leave the fleet as `make up` would: every device reporting, random flapping back on. */
import { fleet } from "./fleet";

export default async function globalTeardown() {
  try {
    fleet.recover("all");
    fleet.unfreeze();
  } catch (e) {
    console.warn("[global-teardown] could not restore the fleet:", (e as Error).message);
  }
}
