# Organograma do time (aba "Home") — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Renderizar o organograma do time da Indicium (3 grupos × pessoas × {nome, papel}) nativo e theme-aware no topo da aba Guia, renomeando o rótulo da aba para "Home".

**Architecture:** Componente presentacional puro (`OrganogramaSection`) lê um dado estático (`organograma.ts`) — sem backend, sem fetch, sem react-query. Avatar de iniciais como fallback; foto (quando o arquivo existir) resolvida por `import.meta.glob` a partir do email sanitizado. Embutido no topo da `GuiaView`; rótulo da aba `guia` vira "Home" (path `/guia` e landing default inalterados).

**Tech Stack:** React + TypeScript + Vite; CSS em `styles.css` com tokens de tema; testes `.test.mts` standalone (node:assert), rodados com `node` (Node 24 faz type-stripping nativo).

## Global Constraints

- **Frontend apenas** — nenhuma mudança em `backend/main.py`.
- **Theme-aware** — cores só via tokens CSS existentes (`var(--panel2)`, `var(--line)`, `var(--ink)`, `var(--mut)`, `var(--accent)`); nada hard-coded.
- **Sem novas dependências** (nada em `package.json`).
- **Helpers puros ficam livres de Vite** (`organograma.ts` não usa `import.meta.glob` — isso vive no componente) para serem testáveis sob `node`.
- **`npx tsc --noEmit` limpo** ao fim de cada task que toca `.ts`/`.tsx`.
- Todos os comandos rodam de `egps_analysis/app/frontend/`.

---

### Task 1: Dado estático + helpers puros (`organograma.ts`) + testes

**Files:**
- Create: `egps_analysis/app/frontend/src/organograma.ts`
- Test: `egps_analysis/app/frontend/organograma.test.mts`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `interface OrgPessoa { nome: string; papel: string; email: string }`
  - `interface OrgGrupo { titulo: string; pessoas: OrgPessoa[] }`
  - `const ORGANOGRAMA: OrgGrupo[]`
  - `function iniciais(nome: string): string`
  - `function fotoKey(email: string): string | null`

- [ ] **Step 1: Write the failing test**

Create `egps_analysis/app/frontend/organograma.test.mts`:

```ts
import assert from "node:assert/strict";
import { iniciais, fotoKey, ORGANOGRAMA } from "./src/organograma.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("iniciais: 1ª + última palavra", () => {
  assert.equal(iniciais("Silas Moura"), "SM");
  assert.equal(iniciais("João Marcos Cunha"), "JC");
});
check("iniciais: uma palavra e espaços extras", () => {
  assert.equal(iniciais("Cher"), "CH");
  assert.equal(iniciais("  Ana  Beatriz  "), "AB");
});
check("fotoKey: sanitiza email (@→_at_, .→_, .png)", () => {
  assert.equal(fotoKey("guilherme.zanotelli@indicium.tech"), "guilherme_zanotelli_at_indicium_tech.png");
  assert.equal(fotoKey("bob@indicium.ai"), "bob_at_indicium_ai.png");
});
check("fotoKey: vazio/sem @ → null", () => {
  assert.equal(fotoKey(""), null);
  assert.equal(fotoKey("   "), null);
  assert.equal(fotoKey("semarroba"), null);
});
check("ORGANOGRAMA: 3 grupos, 15 pessoas", () => {
  assert.equal(ORGANOGRAMA.length, 3);
  assert.equal(ORGANOGRAMA.reduce((n, g) => n + g.pessoas.length, 0), 15);
});
console.log(`\n${pass} testes OK`);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node organograma.test.mts`
Expected: FAIL — `Cannot find module './src/organograma.ts'`.

- [ ] **Step 3: Write the implementation**

Create `egps_analysis/app/frontend/src/organograma.ts`:

```ts
// Organograma do time (aba "Home"): dado estático + helpers PUROS (sem Vite/rede) p/ serem
// testáveis sob node. A resolução de foto (import.meta.glob) fica no componente (Vite-only).

export interface OrgPessoa { nome: string; papel: string; email: string } // email: chave da foto
export interface OrgGrupo  { titulo: string; pessoas: OrgPessoa[] }

// nome + papel confirmados; email = "" em v1 (→ iniciais), preenchido de sas_analistas (Task 5).
export const ORGANOGRAMA: OrgGrupo[] = [
  { titulo: "Time de Gestão", pessoas: [
    { nome: "Silas Moura", papel: "Delivery Manager", email: "" },
    { nome: "Ricardo Onohara", papel: "Consulting Director", email: "" },
    { nome: "Alexandre Rici", papel: "Account Manager", email: "" },
    { nome: "Francielly Miranda", papel: "Project Analyst", email: "" },
    { nome: "Morgana Hübner", papel: "Project Analyst", email: "" },
  ] },
  { titulo: "Lideranças Técnicas", pessoas: [
    { nome: "Lucas Muller", papel: "Tech Lead", email: "" },
    { nome: "Guilherme Zanotelli", papel: "Tech Lead", email: "" },
    { nome: "Eduardo Vieira", papel: "Team Lead", email: "" },
  ] },
  { titulo: "Time de Desenvolvimento", pessoas: [
    { nome: "Hiroto Tanaka", papel: "DE", email: "" },
    { nome: "Julian Vital", papel: "DE", email: "" },
    { nome: "David Couto", papel: "DE", email: "" },
    { nome: "João Marcos Cunha", papel: "DE", email: "" },
    { nome: "Sérgio Pedroso", papel: "AE", email: "" },
    { nome: "Gabriel Amante", papel: "AE", email: "" },
    { nome: "João Emanuel Targino", papel: "AE", email: "" },
  ] },
];

// Iniciais p/ o avatar-fallback: 1ª letra da 1ª e da última palavra (1 palavra → 2 primeiras).
export function iniciais(nome: string): string {
  const t = nome.trim().split(/\s+/).filter(Boolean);
  if (t.length === 0) return "?";
  const s = t.length === 1 ? t[0].slice(0, 2) : t[0][0] + t[t.length - 1][0];
  return s.toUpperCase();
}

// Nome do arquivo de foto derivado do email (chave estável). "" / sem @ → null (→ iniciais).
// Regra: trim + lower-case, "@"→"_at_", "."→"_", sufixo ".png".
export function fotoKey(email: string): string | null {
  const e = email.trim().toLowerCase();
  if (!e || !e.includes("@")) return null;
  return e.replace("@", "_at_").replaceAll(".", "_") + ".png";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node organograma.test.mts`
Expected: PASS — `5 testes OK`.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit`
Expected: no output (clean).

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/organograma.ts egps_analysis/app/frontend/organograma.test.mts
git commit -m "feat(app): dado + helpers do organograma (iniciais, fotoKey) + testes"
```

---

### Task 2: Componente `OrganogramaSection` + CSS

**Files:**
- Create: `egps_analysis/app/frontend/src/components/OrganogramaSection.tsx`
- Create: `egps_analysis/app/frontend/src/assets/organograma/.gitkeep` (pasta das fotos; vazia em v1)
- Modify: `egps_analysis/app/frontend/src/styles.css` (append; namespace `.org-*`)

**Interfaces:**
- Consumes: `ORGANOGRAMA`, `iniciais`, `fotoKey` de `../organograma` (Task 1).
- Produces: `function OrganogramaSection(): JSX.Element` (sem props).

- [ ] **Step 1: Criar a pasta de assets (vazia)**

```bash
mkdir -p egps_analysis/app/frontend/src/assets/organograma
touch egps_analysis/app/frontend/src/assets/organograma/.gitkeep
```

(A pasta precisa existir p/ `import.meta.glob` não avisar; v1 sobe sem nenhuma foto → todos em iniciais.)

- [ ] **Step 2: Criar o componente**

Create `egps_analysis/app/frontend/src/components/OrganogramaSection.tsx`:

```tsx
import { ORGANOGRAMA, iniciais, fotoKey } from "../organograma";

// Fotos (opcionais): arquivos em src/assets/organograma/<email-sanitizado>.png. import.meta.glob
// monta o mapa no bundle; v1 sem arquivos → mapa vazio → todos em iniciais. Adicionar foto depois
// = soltar o arquivo com o nome-padrão (zero código).
const FOTOS = import.meta.glob("../assets/organograma/*.png", {
  eager: true, query: "?url", import: "default",
}) as Record<string, string>;
const fotoPorArquivo = new Map<string, string>(
  Object.entries(FOTOS).map(([path, url]) => [path.split("/").pop()!, url]),
);
function urlFoto(email: string): string | undefined {
  const k = fotoKey(email);
  return k ? fotoPorArquivo.get(k) : undefined;
}

export function OrganogramaSection() {
  return (
    <section className="org">
      <h2 className="org-title">Time Indicium</h2>
      <div className="org-grid">
        {ORGANOGRAMA.map((g) => (
          <div className="org-col" key={g.titulo}>
            <h3 className="org-col-title">{g.titulo}</h3>
            {g.pessoas.map((p) => {
              const foto = urlFoto(p.email);
              return (
                <div className="org-card" key={p.nome}>
                  <div className="org-avatar">
                    {foto
                      ? <img src={foto} alt={p.nome} />
                      : <span className="org-initials">{iniciais(p.nome)}</span>}
                  </div>
                  <div className="org-info">
                    <div className="org-nome">{p.nome}</div>
                    <div className="org-papel">{p.papel}</div>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="org-legend">DE = Data Engineer · AE = Analytics Engineer</div>
    </section>
  );
}
```

- [ ] **Step 3: Adicionar o CSS**

Append em `egps_analysis/app/frontend/src/styles.css`:

```css
/* --- Organograma (aba Home) --- */
.org { display: flex; flex-direction: column; gap: 14px; }
.org-title { margin: 0; font-size: 19px; }
.org-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
.org-col { display: flex; flex-direction: column; gap: 12px; padding: 0 4px; }
.org-col:not(:first-child) { border-left: 1px dashed var(--line); padding-left: 18px; }
.org-col-title { margin: 0 0 4px; font-size: 14px; color: var(--mut); text-align: center; }
.org-card { display: flex; align-items: center; gap: 10px; }
.org-avatar { flex: 0 0 auto; width: 44px; height: 44px; border-radius: 50%; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: var(--panel2); border: 1px solid var(--line); }
.org-avatar img { width: 100%; height: 100%; object-fit: cover; }
.org-initials { font-size: 14px; font-weight: 600; color: var(--accent); }
.org-nome { font-size: 13px; font-weight: 600; color: var(--ink); }
.org-papel { font-size: 12px; color: var(--mut); }
.org-legend { font-size: 11px; color: var(--mut); }
/* Telas estreitas: some a divisória (colunas empilham) */
@media (max-width: 640px) { .org-col:not(:first-child) { border-left: 0; padding-left: 4px; } }
```

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit`
Expected: no output (clean). (Confirma que o `import.meta.glob` e o componente tipam OK.)

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/frontend/src/components/OrganogramaSection.tsx egps_analysis/app/frontend/src/assets/organograma/.gitkeep egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): componente OrganogramaSection + estilos (avatar iniciais/foto)"
```

---

### Task 3: Embutir na `GuiaView` + renomear rótulo p/ "Home"

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/GuiaView.tsx` (import + render no topo, ~linha 1 e ~135)
- Modify: `egps_analysis/app/frontend/src/routes.ts:16` (label)

**Interfaces:**
- Consumes: `OrganogramaSection` de `./OrganogramaSection` (Task 2).
- Produces: nada novo (só fiação).

- [ ] **Step 1: Importar o componente na GuiaView**

Em `egps_analysis/app/frontend/src/components/GuiaView.tsx`, adicionar o import junto aos demais imports do topo (logo após `import type { View } from "../routes";`):

```tsx
import { OrganogramaSection } from "./OrganogramaSection";
```

- [ ] **Step 2: Renderizar no topo da aba**

Em `GuiaView.tsx`, o `return` começa (~linha 134):

```tsx
  return (
    <div className="guia">
```

Inserir `<OrganogramaSection />` como primeiro filho, logo após `<div className="guia">`:

```tsx
  return (
    <div className="guia">
      <OrganogramaSection />
```

- [ ] **Step 3: Renomear o rótulo da aba**

Em `egps_analysis/app/frontend/src/routes.ts:16`, trocar o label (manter `id`/`slug`):

```tsx
  { id: "guia", label: "Home", slug: "guia" },
```

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit`
Expected: no output (clean).

- [ ] **Step 5: Verificação visual (app rodando)**

Subir o app local (de `egps_analysis/app/`): `./local_app.sh start all` — ou, se já rodando, o Vite faz HMR. Abrir http://localhost:5173, clicar na aba **"Home"**:
- Organograma no topo, 3 colunas (Gestão / Lideranças Técnicas / Desenvolvimento) com todos os 15 nomes e cargos, avatares em **iniciais**.
- Divisórias tracejadas entre colunas; legenda DE/AE ao pé; conteúdo do Guia abaixo.
- Alternar tema (☀/🌙) — cores acompanham.
- Estreitar a janela → colunas reflui **sem scroll horizontal**.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GuiaView.tsx egps_analysis/app/frontend/src/routes.ts
git commit -m "feat(app): organograma no topo da aba (Guia→\"Home\")"
```

---

### Task 4: Popular emails a partir de `sas_analistas` (prep p/ fotos)

Independe do visual (v1 já funciona com iniciais). Emails só passam a "pesar" quando houver fotos; baká-los agora mantém o "soltar arquivo = zero código" verdadeiro.

**Files:**
- Modify: `egps_analysis/app/frontend/src/organograma.ts` (preencher `email` por pessoa)

**Interfaces:**
- Consumes: dados de `GET /api/analistas?incluir_inativos=true` (nome, email) — mesma fonte da aba Gestão → "Gestão de analistas".
- Produces: nada novo (só dados preenchidos).

- [ ] **Step 1: Obter a lista de analistas**

Com o app local no ar (`./local_app.sh start back`), listar nome+email dos analistas. Não usar `curl` direto (bloqueado): usar o helper do script ou um pequeno script python do venv que consulte a tabela. Ex. (de `egps_analysis/`):

```bash
./venv/bin/python - <<'PY'
import os, urllib.request, json
os.environ  # backend já no ar em :8000
with urllib.request.urlopen("http://localhost:8000/api/analistas?incluir_inativos=true", timeout=30) as r:
    for a in json.load(r)["rows"]:
        print(a["nome"], "|", a["email"])
PY
```

- [ ] **Step 2: Casar por nome e preencher `email` em `organograma.ts`**

Para cada pessoa do `ORGANOGRAMA`, achar o email correspondente pelo nome (atenção a nome parcial vs. completo, ex.: "Guilherme Zanotelli" pode aparecer como "Guilherme Zanotelli dos Santos"). Preencher o campo `email`. Quem **não** estiver em `sas_analistas` (tipicamente papéis de gestão) fica com `email: ""`.

- [ ] **Step 3: Sinalizar lacunas ao usuário**

Listar para o usuário as pessoas sem email encontrado (as que ficaram `""`), pedindo o endereço (domínio varia: `@indicium.ai` / `@indicium.tech`). Não bloqueia o merge — esses seguem em iniciais até serem preenchidos.

- [ ] **Step 4: Typecheck + testes**

Run: `npx tsc --noEmit` (limpo) e `node organograma.test.mts` (o teste de contagem 3 grupos/15 pessoas segue passando).

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/frontend/src/organograma.ts
git commit -m "chore(app): emails do organograma a partir de sas_analistas"
```

---

## Notas de execução

- **Fotos (fora de escopo v1):** quando os headshots chegarem, salvar cada um em `src/assets/organograma/` nomeado pelo email sanitizado (ex.: `guilherme_zanotelli_at_indicium_tech.png`), rebuildar — aquele card passa a mostrar a foto, sem tocar código.
- **App derrubado:** o ambiente local caiu entre sessões; subir com `./local_app.sh start all` (de `egps_analysis/app/`) antes das verificações visuais / da Task 4.
