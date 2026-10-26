# Light/Dark mode (paleta Indicium) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar tema claro/escuro com a paleta Indicium e um toggle no topbar; default segue o SO, escolha manual lembrada.

**Architecture:** CSS variables + atributo `data-theme` no `<html>` (`:root`=dark, `[data-theme="light"]` sobrescreve). Lógica de tema em `theme.ts` (pura/testável). Toggle no `App.tsx`. Script inline no `index.html` aplica o tema antes do CSS (anti-flash).

**Tech Stack:** React 18 + TypeScript/Vite, CSS custom properties.

---

## File Structure

| Arquivo | Mudança | Responsabilidade |
|---|---|---|
| `egps_analysis/app/frontend/src/theme.ts` | criar | `Theme`, `resolveInitialTheme`, `applyTheme`. |
| `egps_analysis/app/frontend/theme.test.mts` | criar | teste Node de `resolveInitialTheme` (fora de `src/`). |
| `egps_analysis/app/frontend/src/styles.css` | modificar | `:root` recolorido + bloco `[data-theme="light"]` + trocar hex hardcoded por tokens + `.theme-btn`/`.who`. |
| `egps_analysis/app/frontend/index.html` | modificar | script anti-flash no `<head>`. |
| `egps_analysis/app/frontend/src/App.tsx` | modificar | estado + botão de toggle no topbar. |

---

### Task 1: `theme.ts` (lógica pura) — TDD

**Files:**
- Create: `egps_analysis/app/frontend/src/theme.ts`
- Test: `egps_analysis/app/frontend/theme.test.mts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `egps_analysis/app/frontend/theme.test.mts`:
```ts
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
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd egps_analysis/app/frontend && node theme.test.mts`
Expected: FAIL — `Cannot find module './src/theme.ts'`. (Node 24 faz type-stripping; se reclamar, use `node --experimental-strip-types theme.test.mts`.)

- [ ] **Step 3: Implementar `src/theme.ts`**
```ts
export type Theme = "light" | "dark";

export function resolveInitialTheme(stored: string | null, prefersLight: boolean): Theme {
  if (stored === "light" || stored === "dark") return stored;
  return prefersLight ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("theme", theme);
  } catch (e) {
    /* localStorage indisponível — ignora */
  }
}
```

- [ ] **Step 4: Rodar e confirmar passa**

Run: `node theme.test.mts`
Expected: `3 testes OK`, exit 0.

- [ ] **Step 5: Build verde**

Run: `npm run build`
Expected: sem erros (`theme.ts` em `src/` é type-checado; `theme.test.mts` fora de `src/` é ignorado pelo tsc).

- [ ] **Step 6: Commit** (SEM trailer Co-Authored-By)
```bash
git add egps_analysis/app/frontend/src/theme.ts egps_analysis/app/frontend/theme.test.mts
git commit -m "feat(app/front): theme.ts (resolve/apply tema) + teste"
```

---

### Task 2: Tokenizar `styles.css` (dark recolorido + tema claro)

**Files:**
- Modify: `egps_analysis/app/frontend/src/styles.css`

- [ ] **Step 1: Substituir o bloco `:root` (linhas 1–12) por:**
```css
:root {
  --bg: #1c1d2f;
  --panel: #25273b;
  --panel2: #2f3150;
  --ink: #f5f6fa;
  --mut: #9a9cc0;
  --line: #3a3c5c;
  --line-soft: #2a2c46;
  --hover: #2a2c46;
  --track: #3a3c5c;
  --surface-3: #222438;
  --accent: #3a58ee;
  --accent2: #699bfb;
  --on-accent: #ffffff;
  --ok: #4caf72;
  --danger: #e0594f;
  --warn: #e6b450;
  --diverge: #2f2a1e;
  --tone-ok-bg: #1f3a2a; --tone-ok-fg: #7fd6a0;
  --tone-wip-bg: #3a341c; --tone-wip-fg: #e6c84e;
  --tone-cyc-bg: #3a2222; --tone-cyc-fg: #ffb0a8; --tone-cyc-border: #ff7a6e;
  --tone-indi-bg: #18324a; --tone-indi-fg: #8fc7ff; --tone-indi-border: #1f496b;
  --tone-ext-bg: #3a2f18; --tone-ext-border: #5a4a1c;
  --danger-soft: #f0a8a2;
  --fill-muted: #5b6370;
}

[data-theme="light"] {
  --bg: #ffffff;
  --panel: #ffffff;
  --panel2: #f1f0fa;
  --ink: #1c1d2f;
  --mut: #5a5c74;
  --line: #dedaf4;
  --line-soft: #ececf4;
  --hover: #f5f5fb;
  --track: #e6e4f2;
  --surface-3: #f7f6fc;
  --accent: #3a58ee;
  --accent2: #699bfb;
  --on-accent: #ffffff;
  --ok: #1e8e4f;
  --danger: #c0392b;
  --warn: #9a7d12;
  --diverge: #fbf3e0;
  --tone-ok-bg: #e3f5ea; --tone-ok-fg: #1e8e4f;
  --tone-wip-bg: #fbf3d6; --tone-wip-fg: #8a6d0f;
  --tone-cyc-bg: #fde4e2; --tone-cyc-fg: #c0392b; --tone-cyc-border: #e0594f;
  --tone-indi-bg: #e4ecfe; --tone-indi-fg: #2a44c0; --tone-indi-border: #bcd0fb;
  --tone-ext-bg: #fbf0d6; --tone-ext-border: #e6d9a8;
  --danger-soft: #c0392b;
  --fill-muted: #b9b6cc;
}
```

- [ ] **Step 2: Trocar os hex hardcoded por tokens (replace-all no corpo do arquivo, linhas 13+).**

Aplicar cada substituição (todas as ocorrências), EXCETO os 2 casos especiais marcados:

| Hex atual | Trocar por |
|---|---|
| `#23272e` | `var(--line-soft)` |
| `#20242b` | `var(--hover)` |
| `#2a2520` | `var(--diverge)` |
| `#2a2f37` | `var(--track)` |
| `#1a1d23` | `var(--surface-3)` |
| `#1f3a2a` | `var(--tone-ok-bg)` |
| `#7fd6a0` | `var(--tone-ok-fg)` |
| `#3a341c` | `var(--tone-wip-bg)` |
| `#e6c84e` | `var(--tone-wip-fg)` |
| `#3a2222` | `var(--tone-cyc-bg)` |
| `#3a2422` | `var(--tone-cyc-bg)` |
| `#ffb0a8` | `var(--tone-cyc-fg)` |
| `#ffd9d6` | `var(--tone-cyc-fg)` |
| `#b06a64` | `var(--tone-cyc-fg)` |
| `#ff7a6e` | `var(--tone-cyc-border)` |
| `#f0a8a2` | `var(--danger-soft)` |
| `#1e2a44` | `var(--tone-indi-bg)` |
| `#18324a` | `var(--tone-indi-bg)` |
| `#14283b` | `var(--tone-indi-bg)` |
| `#9ec1ff` | `var(--tone-indi-fg)` |
| `#8fc7ff` | `var(--tone-indi-fg)` |
| `#1f496b` | `var(--tone-indi-border)` |
| `#3a2f18` | `var(--tone-ext-bg)` |
| `#3a2f1c` | `var(--tone-ext-bg)` |
| `#302713` | `var(--tone-ext-bg)` |
| `#5a4a1c` | `var(--tone-ext-border)` |
| `#5b6370` | `var(--fill-muted)` |

**Casos especiais (NÃO use replace-all cego):**
- `#fff`: trocar por `var(--on-accent)` em TODAS as ocorrências, **exceto** na regra `.tabs button.on, .tabs a.on` (linha 83), onde deve virar `var(--ink)` (senão o texto da aba ativa some no tema claro, pois `--panel2` fica claro).
- **Não tocar** em `.lin-canvas { background: #fafafa }` (linha 103) nem na cor `rgba(17, 19, 24, .96)` de `.lin-tip` (linha 106) — grafo/tooltip ficam fixos nos 2 temas.

- [ ] **Step 3: Adicionar estilos do toggle ao final do `styles.css`:**
```css
/* toggle de tema */
.who { display: flex; align-items: center; gap: 10px; }
.theme-btn { background: transparent; color: var(--ink); border: 1px solid var(--line);
  border-radius: 6px; padding: 3px 9px; font-size: 14px; cursor: pointer; line-height: 1; }
.theme-btn:hover { border-color: var(--mut); }
```

- [ ] **Step 4: Conferir que não sobrou hex hardcoded (fora das 2 exceções)**

Run: `cd egps_analysis/app/frontend/src && grep -nE '#[0-9a-fA-F]{3,6}' styles.css | grep -vE 'fafafa|rgba|17, 19, 24'`
Expected: só aparecem linhas DENTRO de `:root`/`[data-theme="light"]` (as definições de token). Nenhum hex solto no corpo.

- [ ] **Step 5: Build verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: sem erros.

- [ ] **Step 6: Commit**
```bash
git add egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app/front): tokeniza cores + tema claro (paleta Indicium)"
```

---

### Task 3: Script anti-flash no `index.html`

**Files:**
- Modify: `egps_analysis/app/frontend/index.html`

- [ ] **Step 1: Inserir o script no `<head>`** (logo após a linha `<title>...</title>`):
```html
    <script>
      (function () {
        try {
          var s = localStorage.getItem('theme');
          var t = (s === 'light' || s === 'dark') ? s
                : (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
          document.documentElement.setAttribute('data-theme', t);
        } catch (e) {}
      })();
    </script>
```

- [ ] **Step 2: Build e confirmar que o script foi pro `static/index.html`**

Run: `cd egps_analysis/app/frontend && npm run build && grep -c "prefers-color-scheme" ../static/index.html`
Expected: build verde; grep retorna `1`.

- [ ] **Step 3: Commit**
```bash
git add egps_analysis/app/frontend/index.html egps_analysis/app/static/index.html
git commit -m "feat(app/front): script anti-flash de tema no index.html"
```

---

### Task 4: Toggle no `App.tsx`

**Files:**
- Modify: `egps_analysis/app/frontend/src/App.tsx`

- [ ] **Step 1: Import** (junto dos outros imports do topo):
```tsx
import { resolveInitialTheme, applyTheme, type Theme } from "./theme";
```

- [ ] **Step 2: Estado + toggle + listener** — dentro de `App()`, após os outros `useState`:
```tsx
  const [theme, setTheme] = useState<Theme>(
    () =>
      (document.documentElement.getAttribute("data-theme") as Theme | null) ??
      resolveInitialTheme(
        localStorage.getItem("theme"),
        window.matchMedia("(prefers-color-scheme: light)").matches,
      ),
  );

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  }

  // sem escolha manual salva → acompanha o sistema ao vivo
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem("theme")) setTheme(e.matches ? "light" : "dark");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
```

- [ ] **Step 3: Botão no topbar** — trocar a `<div className="who">...</div>` por:
```tsx
        <div className="who">
          <button className="theme-btn" onClick={toggleTheme} aria-label="Alternar tema" title="Tema claro/escuro">
            {theme === "dark" ? "☀" : "🌙"}
          </button>
          {user ? `👤 ${user}` : ""}
        </div>
```

- [ ] **Step 4: Build verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: sem erros de tipo (`MediaQueryListEvent` é tipo DOM global; `Theme` importado).

- [ ] **Step 5: Commit**
```bash
git add egps_analysis/app/frontend/src/App.tsx egps_analysis/app/static
git commit -m "feat(app/front): toggle de tema claro/escuro no topbar"
```

---

### Task 5: Operação — rebuild + deploy (gate humano)

**Files:** nenhum (operação; disparar só com OK do usuário).

- [ ] **Step 1: Rebuild + sync + deploy**
```bash
cd egps_analysis/app/frontend && npm run build && cd ..
databricks sync . /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas \
  --exclude 'frontend/node_modules/**' --exclude '.databricks/**' --profile bv
databricks apps deploy monitoramento-sas \
  --source-code-path /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas --profile bv
```
Expected: deployment `SUCCEEDED`.

- [ ] **Step 2: Checagem manual** — abrir o app (hard-refresh): toggle ☀/🌙 alterna; recarregar mantém a escolha; varrer as abas no **claro** conferindo que nada some (pills/chips/barras/bordas/hovers/selects). Testar `prefers-color-scheme` do SO na 1ª visita (limpar `localStorage.theme`).

---

## Fora do plano
Tipografia Inter/Roboto Mono, grafo de Linhagem, logo Indicium.

## Self-review (preenchido)
- **Cobertura do spec:** mecanismo data-theme+vars → Task 2/3; theme.ts puro → Task 1; toggle topbar + matchMedia → Task 4; anti-flash → Task 3; tokens neutros+semânticos (ambos os temas) → Task 2; rebuild/deploy → Task 5. ✓
- **Placeholders:** nenhum; cada passo tem código/comando + resultado esperado; a tabela de substituição cobre todos os hex levantados.
- **Consistência:** tokens definidos no `:root`/`[data-theme]` (Task 2 Step 1) são exatamente os usados na tabela de substituição (Step 2) e no `.theme-btn` (Step 3). `resolveInitialTheme`/`applyTheme`/`Theme` de `theme.ts` (Task 1) batem com os imports/usos no `App.tsx` (Task 4). O `data-theme` setado pelo script (Task 3) é lido pelo estado inicial do `App.tsx` (Task 4 Step 2).
