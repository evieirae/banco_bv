import assert from "node:assert/strict";
import { resolveInitialTheme } from "./src/theme.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("stored válido prevalece sobre o sistema", () => {
  assert.equal(resolveInitialTheme("light", false), "light");
  assert.equal(resolveInitialTheme("dark", true), "dark");
});
check("sem stored segue o sistema", () => {
  assert.equal(resolveInitialTheme(null, true), "light");
  assert.equal(resolveInitialTheme(null, false), "dark");
});
check("stored inválido cai no sistema", () => {
  assert.equal(resolveInitialTheme("", true), "light");
  assert.equal(resolveInitialTheme("bogus", false), "dark");
});
console.log(`\n${pass} testes OK`);
