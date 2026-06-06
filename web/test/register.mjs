// Registers the module-customization hook that stubs the MediaPipe CDN import,
// so pose.js (and app.js, which imports it) can be loaded under `node --test`.
// Used via `node --import ./test/register.mjs`.
import { register } from "node:module";

register("./cdn-stub.mjs", import.meta.url);
