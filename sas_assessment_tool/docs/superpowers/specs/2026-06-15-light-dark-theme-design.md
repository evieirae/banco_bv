# Design — Light/Dark mode com paleta Indicium

**Data:** 2026-06-15
**Componente:** `egps_analysis/app/frontend` (React/TS + CSS)
**Status:** aprovado para implementação

## 1. Objetivo

Adicionar **tema claro e escuro** ao app, com a paleta da **Indicium AI** aplicada aos dois
temas, e um **toggle** no topbar. Default segue o sistema operacional; a escolha manual é lembrada.

## 2. Decisões (do brainstorming)

| Tema | Decisão |
|---|---|
| Escopo | Recolorir **ambos** os temas para a paleta Indicium. **Manter** fontes do sistema (sem Inter/Roboto Mono). |
| Default | Seguir `prefers-color-scheme`; escolha manual via toggle **prevalece** e é salva em `localStorage` (`theme`). |
| Mecanismo | CSS variables + atributo `data-theme="light"\|"dark"` no `<html>`. `:root` = dark (default); bloco `[data-theme="light"]` sobrescreve os tokens. |
| Anti-flash | Script inline no `<head>` do `index.html` seta `data-theme` antes do CSS pintar. |
| Toggle | Botão ☀/🌙 no topbar (ao lado do `👤 user`). |

## 3. Arquitetura

### 3.1 `src/theme.ts` (novo — lógica pura, testável)
```
type Theme = "light" | "dark";
resolveInitialTheme(stored: string | null, prefersLight: boolean): Theme
  // stored válido ("light"/"dark") prevalece; senão prefersLight ? "light" : "dark"
applyTheme(theme: Theme): void
  // document.documentElement.setAttribute("data-theme", theme) + localStorage.setItem("theme", theme)
```
`resolveInitialTheme` é puro (testável em Node, como `egpList`/roteamento).

### 3.2 Toggle no `App.tsx`
- Estado `theme` inicializado de `document.documentElement.getAttribute("data-theme")` (já setado pelo script inline) ou `resolveInitialTheme`.
- Botão no topbar: alterna `light`↔`dark`, chama `applyTheme`, atualiza estado. Ícone ☀ (no dark, "ir p/ claro") / 🌙 (no light).
- `matchMedia('(prefers-color-scheme)')` listener atualiza o tema **apenas enquanto não houver escolha manual** (sem `localStorage.theme`).

### 3.3 Anti-flash em `frontend/index.html`
Script inline no `<head>`, antes do bundle:
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
*(Fallback se a CSP do Databricks App bloquear inline script — improvável p/ HTML próprio: setar no topo do `main.tsx`, com flash mínimo de 1 frame.)*

## 4. Tokens (em `styles.css`)

### 4.1 Estruturais / neutros

| Token | Dark (`:root`) | Light (`[data-theme="light"]`) | Uso |
|---|---|---|---|
| `--bg` | `#1c1d2f` | `#ffffff` | canvas |
| `--panel` | `#25273b` | `#ffffff` | cards |
| `--panel2` | `#2f3150` | `#f1f0fa` | headers/superfícies sutis |
| `--ink` | `#f5f6fa` | `#1c1d2f` | texto |
| `--mut` | `#9a9cc0` | `#5a5c74` | texto fraco |
| `--line` | `#3a3c5c` | `#dedaf4` | bordas |
| `--line-soft` (novo, =`#23272e` ×6) | `#23272e` | `#ececf4` | bordas internas de linha |
| `--hover` (novo, =`#20242b` ×4) | `#20242b` | `#f5f5fb` | hover de linha |
| `--track` (novo, =`#2a2f37` ×3) | `#2a2f37` | `#e6e4f2` | trilho de barra |
| `--surface-3` (novo, =`#1a1d23`) | `#1a1d23` | `#f7f6fc` | rd-expand |
| `--accent` | `#3a58ee` | `#3a58ee` | CTA/ativo/links (ambos) |
| `--accent2` (novo) | `#699bfb` | `#699bfb` | hover/secundário |
| `--on-accent` (novo, =`#fff`) | `#ffffff` | `#ffffff` | texto sobre accent |
| `--ok` | `#4caf72` | `#1e8e4f` | fills/semântico |
| `--danger` | `#e0594f` | `#c0392b` | fills/semântico |
| `--warn` | `#e6b450` | `#9a7d12` | fills/semântico |

### 4.2 Pares de tom semântico (pills/chips/badges)
Cada tom tem **bg** + **fg**. Substituir os hex hardcoded por estes tokens.

| Tom | Dark bg / fg | Light bg / fg | Onde |
|---|---|---|---|
| ok | `#1f3a2a` / `#7fd6a0` | `#e3f5ea` / `#1e8e4f` | `.pill.ok`, `.chip.ok`, `.c-new` (fg) |
| wip | `#3a341c` / `#e6c84e` | `#fbf3d6` / `#8a6d0f` | `.pill.wip`, `.chip.wip` |
| todo | `#2a2f37` / `var(--mut)` | `#eef0f4` / `var(--mut)` | `.pill.todo`, `.chip.todo` |
| cyc | `#3a2222` / `#ffb0a8` | `#fde4e2` / `#c0392b` | `.pill.cyc`, `.cyc-txt`, `.chip.cyc` |
| indi | `#18324a` / `#8fc7ff` | `#e4ecfe` / `#2a44c0` | `.pill.ind`, `.dep-b.indi`, `.dep-chip.indi` |
| ext | `#3a2f18` / `#e6c84e` | `#fbf0d6` / `#8a6d0f` | `.dep-b.ext`, `.dep-chip.ext` |
| danger-soft (fg) | `#f0a8a2` | `#c0392b` | `.st-todo` select, `.c-old`, `.chip.todo` fg |

Tokens adicionais para casos pontuais: `.cyc-warn` bg (`#3a2222`→`var(--tone-cyc-bg)`, texto `#ffd9d6`→`var(--tone-cyc-fg)`), `.rd-fill.cyc` (`#b06a64`), `.wave-fill.todo` (`#5b6370`), bordas de `.dep-chip` (`#1f496b`/`#5a4a1c`/`#ff7a6e`) → mapear p/ os tokens de tom correspondentes (border = fg-escurecido ou o próprio fg).

Valores do tema claro são **pontos de calibração**: ajustar para contraste AA legível sobre branco (ver §7).

### 4.3 Fora da tokenização
- `.lin-canvas { background: #fafafa }` — canvas do grafo cytoscape, claro de propósito nos dois temas. **Mantido.**

## 5. Arquivos tocados
- `src/styles.css` — recolorir `:root`, adicionar bloco `[data-theme="light"]`, novos tokens, e **trocar todos os hex hardcoded** (§4) por tokens.
- `src/theme.ts` — **novo**.
- `src/App.tsx` — estado + botão de toggle no topbar.
- `frontend/index.html` — script anti-flash no `<head>`.
- `styles.css` ganha estilos do botão de toggle (`.theme-btn`).

## 6. Fora de escopo (YAGNI)
- Tipografia Inter/Roboto Mono. Recolorir o grafo de Linhagem. >2 temas. Logo da Indicium.

## 7. Verificação
- **`theme.ts` puro**: teste em Node (`resolveInitialTheme` cobre: stored válido prevalece; inválido/ausente cai no `prefersLight`).
- **Build**: `npm run build` verde.
- **Manual (dark e light):** alternar pelo toggle; recarregar mantém a escolha (localStorage); 1ª visita segue o SO; varrer as abas (Resumo/Monitoramento/EGPs/Prontidão/Ondas/Linhagem/Histórico) conferindo que **nada some** no claro (texto, pills, chips, barras, bordas, hovers, selects de status) — foco nos tons semânticos calibrados p/ contraste.
- **Revisão adversarial** do diff.

## 8. Custo
Frontend só (sem backend/publish). Rebuild + redeploy. O grosso é a tokenização do `styles.css`.
