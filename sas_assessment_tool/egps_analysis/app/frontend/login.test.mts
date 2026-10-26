import assert from "node:assert/strict";
import { destinoDoLogin } from "./src/login.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const EXPIROU = JSON.stringify({ detail: "Login ausente ou expirado — entre de novo.", entrar: "/login" });

check("sessão expirada na AWS: vai ao login guardando onde estava", () => {
  assert.equal(destinoDoLogin(401, EXPIROU, "/egps/abc", "?aba=inputs"), "/login?volta=%2Fegps%2Fabc%3Faba%3Dinputs");
});
check("401 do Databricks (sem 'entrar') não desvia", () => {
  assert.equal(destinoDoLogin(401, JSON.stringify({ detail: "Autenticação de usuário ausente" }), "/", ""), null);
});
check("403 (sem cadastro) fica na tela de sem acesso", () => {
  assert.equal(destinoDoLogin(403, EXPIROU, "/", ""), null);
});
check("corpo que não é JSON não desvia", () => {
  assert.equal(destinoDoLogin(401, "<html>401</html>", "/", ""), null);
});
console.log(`${pass} ok`);
