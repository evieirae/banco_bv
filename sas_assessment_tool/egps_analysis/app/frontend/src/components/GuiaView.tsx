// Aba "Guia" — onboarding dos analistas: o que o painel faz, de onde vêm os
// dados, os conceitos que aparecem em todas as abas e o papel de cada uma.
// Conteúdo 100% estático (nenhuma chamada de API); é o espelho resumido de
// app/GUIA_DO_APP.md — mudou aba/conceito/fluxo, atualize os dois.
import type { View } from "../routes";
import { OrganogramaSection } from "./OrganogramaSection";

interface AbaCard {
  id: View;
  icon: string;
  label: string;
  desc: string;
  edita: string | null; // o que é editável na aba (null = só leitura)
  gestao?: boolean;     // restrita ao grupo bv_users
}

const ABAS: AbaCard[] = [
  {
    id: "resumo", icon: "📊", label: "Resumo",
    desc: "Visão executiva: funis de migração (EGPs) e de ingestão (inputs), funil por área (DOR1) e inputs por origem — sempre em duas visões: escopo Indicium e “+ dependências”.",
    edita: null,
  },
  {
    id: "monitor", icon: "📥", label: "Inputs",
    desc: "A grade de trabalho da ingestão: um input por linha, seletor de escopo, filtros por categoria/origem/status/área e busca em todas as linhas. Clicar num input mostra quem o produz, quem o consome e o histórico de edições.",
    edita: "Status (humano), Responsável (= ingestão) e Observação",
  },
  {
    id: "outputs", icon: "📤", label: "Outputs",
    desc: "O que os EGPs produzem: produtores, consumidores e se o artefato é Terminal (ninguém consome) ou Intermediário. Só artefatos permanentes entram (temporárias de WORK ficam de fora). Outputs não são migrados — a aba serve para entender dependências.",
    edita: null,
  },
  {
    id: "readiness", icon: "🧩", label: "EGPs",
    desc: "Prontidão de cada EGP para migrar: % de inputs já modernizados, bloqueios (🔒), impacto de dependência despriorizada (⏸), ciclos (⟳) e dependências. O seletor de escopo alterna entre só Indicium, Indicium + dependências e todos. Clicar na linha expande o detalhe (deps navegáveis com selo Migrado/Despriorizado + inputs editáveis + 🔗 link compartilhável).",
    edita: "Etapa, Status e Responsável (= migração) do EGP; inputs no detalhe",
  },
  {
    id: "indicium", icon: "🎯", label: "Escopo",
    desc: "A lista DOR1 editável — fonte do que é/não é Indicium. Adicionar, desativar (✕, reversível com ↺) e reativar EGPs; cada edição re-deriva o escopo no app inteiro na hora.",
    edita: "Entradas do escopo (adicionar/desativar/reativar)",
  },
  {
    id: "waves", icon: "🗓", label: "Priorização",
    desc: "O plano mensal de ingestão (recorte fixo: Indicium + dependências; capacidade ajustável pela gestão, padrão 400 inputs/mês; prazo dez/2026). Ordena por viabilidade → alavancagem → quick win; input compartilhado conta uma vez só. Cards: Migrados, Despriorizados, Bloqueados, Habilitados; a barra de cada mês mostra os EGPs concluídos.",
    edita: "Fixar EGP num mês (📌) e capacidade do plano — só gestão",
  },
  {
    id: "history", icon: "📜", label: "Histórico",
    desc: "Auditoria de todas as edições do painel: quando, quem, aba de origem, campo e valor de → para. Nada muda silenciosamente.",
    edita: null,
  },
  {
    id: "gestao", icon: "👥", label: "Gestão",
    desc: "Gestão de EGPs/Inputs (datas de migração/conversão, dias úteis, status/comentários, gráficos de atribuídos por colaborador — parte verde = concluídos —, convertidos e migrações por mês) + cadastro de analistas, a fonte dos dropdowns de “Responsável”.",
    edita: "Datas de migração, comentários de status e analistas", gestao: true,
  },
];

const CONCEITOS: { t: string; d: string }[] = [
  { t: "EGP", d: "Um projeto SAS (Enterprise Guide) — a unidade de migração." },
  { t: "Input", d: "Tabela/arquivo/script que um EGP consome. “Ingerir” = disponibilizá-lo no BigQuery/lake." },
  { t: "Output", d: "Artefato que um EGP produz. Não é migrado; serve para mapear dependências." },
  { t: "Escopo Indicium", d: "A lista DOR1 de EGPs sob responsabilidade da Indicium (gerida na aba Escopo)." },
  { t: "+ dependências", d: "EGPs fora do escopo cujos outputs alimentam (direta ou indiretamente) EGPs do escopo — o fecho transitivo. Tabela já modernizada ou sanitizada não gera dependência: se tudo o que liga A a B está resolvido, B some como dependência de A." },
  { t: "Origem do input", d: "BigQuery (já no lake) · Transacional (banco corporativo) · SAS/Local dependência (produzido por outro EGP) · SAS/Local externo (“dep. produtor ausente”) · Arquivo · Script." },
  { t: "Status humano × Auto (⚠)", d: "O status editado por vocês sempre prevalece sobre a detecção automática; divergência entre os dois é sinalizada com ⚠, nunca sobrescrita." },
  { t: "Sanitizado", d: "Status terminal do input (“não vai ser migrado”). Continua no universo do escopo (aparece em Resumo e Inputs), mas não conta como pendência de progresso por EGP nem nas waves. Reversível." },
  { t: "Autoprodutor", d: "Status terminal do input para quando o próprio EGP consumidor também CRIA a tabela (não só apensa) — não precisa de ingestão separada. Ao contrário de Sanitizado, CONTA COMO FEITO na prontidão (input e EGP). Um badge “🔁 candidato a autoprodutor” aparece em Inputs quando detectado; a confirmação é manual, pelo mesmo seletor de Status. Reversível." },
  { t: "🔒 Bloqueado", d: "EGP que depende (direta ou transitivamente) de tabela SAS sem produtor mapeado. Destrava quando a tabela for ingerida ou o produtor identificado." },
  { t: "⟳ Ciclo", d: "EGPs em dependência circular (A alimenta B que alimenta A) — precisam ser tratados juntos." },
  { t: "Mês", d: "Posição do EGP no plano da aba Priorização (substituiu a antiga “Onda”). “—” = fora do recorte do plano." },
  { t: "homônimo ×N", d: "Um mesmo nome de tabela SAS que corresponde a N tabelas físicas distintas (caminhos diferentes)." },
];

const FLUXOS: { quero: string; onde: string }[] = [
  { quero: "Marcar um input como ingerido", onde: "Inputs → coluna “Status (humano)”. O ⚠ some quando humano e Auto convergem." },
  { quero: "Marcar um input como não migrável", onde: "Inputs → status “Sanitizado” (segue no escopo, mas fora do progresso por EGP; reversível)." },
  { quero: "Dispensar pré-working de um input que o próprio EGP produz", onde: "Inputs → badge “🔁 candidato a autoprodutor” sinaliza qual EGP cria+consome; confirme em status “Autoprodutor” (vale para todos os EGPs que usam o input; reversível)." },
  { quero: "Atribuir responsáveis", onde: "Inputs → Responsável (ingestão) · EGPs → Responsável (migração)." },
  { quero: "Avançar um EGP no funil de migração", onde: "EGPs → colunas Etapa/Status. “Concluído” = terminou a etapa atual; “Migrado” = terminal (em produção, validado)." },
  { quero: "Saber por que um EGP está bloqueado", onde: "EGPs → clique na linha → seção “🔒 Bloqueado por dependência” + inputs “dep. produtor ausente”." },
  { quero: "Compartilhar um EGP com alguém", onde: "EGPs → detalhe → 🔗 link (URL direta /egps/<nome>)." },
  { quero: "Incluir/tirar um EGP do escopo Indicium", onde: "Escopo → “+ Adicionar” / ✕ (desativa; ↺ reativa)." },
  { quero: "Ver quando um EGP está previsto", onde: "Coluna “Mês” em qualquer aba — o plano vem da Priorização." },
  { quero: "Antecipar/adiar um EGP no plano (gestão)", onde: "Priorização → seletor “Mês” da linha (📌; “auto” volta ao automático)." },
  { quero: "Levar os dados para Excel", onde: "⬇ Exportar CSV (Inputs, Outputs, EGPs, Escopo, Priorização) — exporta o que está exibido; na Priorização, o plano inteiro (1 linha por EGP × mês)." },
  { quero: "Auditar quem mudou o quê", onde: "Histórico (ou o histórico do input, no painel lateral)." },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "Os números de duas abas não batem — é bug?",
    a: "Quase sempre é diferença de recorte: escopo (Indicium × + dependências × base), filtros aplicados e a regra do Sanitizado (segue no universo do escopo em Resumo/Inputs, mas fora do progresso por EGP e das waves). O tooltip de cada card diz qual recorte ele usa. Na aba EGPs, os cards seguem o seletor de escopo, não os filtros de coluna.",
  },
  {
    q: "“X/Y migrados” no funil conta o quê?",
    a: "Conta por status terminal: Migrado + Despriorizado e Contabilizado (esforço resolvido) — não “chegou na última etapa”. Já o card “Migrados neste mês” da Priorização conta só Migrado, no mês de calendário corrente.",
  },
  {
    q: "Marquei um EGP como “Despriorizado e Contabilizado” — o que acontece?",
    a: "Ele continua aparecendo em tudo (inclusive no mês do plano de Priorização, como um EGP normal), mas deixa de puxar dependências — as que só existiam por causa dele saem dos recortes “+ dependências”; as compartilhadas com outro EGP ativo ficam. Quem depende dele ganha o aviso ⏸ na aba EGPs (o output que consome não será produzido pelo plano). Reverter o status traz as dependências de volta na hora e apaga os avisos.",
  },
  {
    q: "Onde foi a aba “Escopo de migração”?",
    a: "Foi fundida na aba EGPs — use o seletor “Indicium + dependências”. Links antigos /escopo-migracao continuam funcionando e abrem a aba EGPs.",
  },
  {
    q: "Onde foi a aba “Linhagem”?",
    a: "Foi desativada (2026-07): o grafo estava defasado em relação às regras de dependência mais novas (escolha de produtor canônico) e será repensado. Para “se eu migrar X, o que destravo?”, use o detalhe do EGP — listas Depende de / Alimenta, navegáveis.",
  },
  {
    q: "Onde foram as abas “Macros” e “Ingestão”?",
    a: "Foram removidas (2026-08): a de Macros era exploratória (handoffs via arquivo com macro no nome, nunca alimentou o grafo) e a de Ingestão não era usada — a atualização do corpus volta a ser feita pelo pipeline fora do app.",
  },
  {
    q: "Onde foi a aba “EGPs Atualizados”?",
    a: "Foi aposentada (2026-09): a versão nova entra no corpus e vira linha da aba EGPs como qualquer outro EGP, com um funil só. O que a aba tinha de único — a comparação com o antecessor (impactos da troca, inputs novos, outputs removidos com consumidor, histórico de versões, autor e data do último save) — virou a seção “Versão atualizada” no detalhe do EGP. Enquanto a versão recebida ainda não entrou no corpus, ela aparece no chip “📥 Aguardando corpus”, na própria aba EGPs. Links antigos /egps-atualizados abrem o Resumo.",
  },
  {
    q: "Por que um EGP mostra “—” na coluna Mês?",
    a: "Ele está fora do recorte do plano (não é Indicium nem dependência do escopo) — a Priorização não o agenda.",
  },
  {
    q: "O que significa “dep. produtor ausente”?",
    a: "A tabela é produzida por um EGP que não está no corpus recebido. O rótulo deixa explícito que falta mapear o produtor (ou receber o EGP), em vez de esconder a tabela entre inputs comuns.",
  },
  {
    q: "Editei e nada mudou em outra aba.",
    a: "Use o ⟳ Atualizar dados no topo. Edições de Escopo e pins de mês propagam sozinhos; alguns agregados usam cache curto (até ~5 min). Em particular, as dependências usam esse cache: marcar um input como Modernizado/Sanitizado (que faz a dependência satisfeita sumir) ou despriorizar um EGP (que liga o aviso ⏸ nos dependentes) pode levar até ~5 min — ou um ⟳ — para refletir na aba EGPs e na Priorização.",
  },
  {
    q: "Posso desfazer uma edição?",
    a: "Sim — edite de volta (o valor anterior está no Histórico). Nada é apagado de verdade: escopo desativa (não deleta), analista desativa, e a auditoria guarda tudo.",
  },
];

export function GuiaView({ isGestao, onNav }: { isGestao: boolean; onNav: (v: View) => void }) {
  return (
    <div className="guia">
      <div className="home-grid">
      <div className="home-main">
      <section className="guia-sec">
        <h2>Como funciona este painel</h2>
        <p className="guia-lead">
          O painel acompanha a migração dos projetos SAS (<strong>EGPs</strong>) para o BigQuery/lake:
          quais tabelas (<strong>inputs</strong>) cada EGP consome, o que já está modernizado, o que
          bloqueia o quê, e um plano mensal de ingestão. Toda edição roda em seu nome e fica auditada.
        </p>
        <div className="guia-flow">
          <div className="guia-step"><span className="guia-step-ico">📦</span><strong>EGPs recebidos</strong><span>projetos .egp enviados pelas áreas</span></div>
          <span className="guia-arrow">→</span>
          <div className="guia-step"><span className="guia-step-ico">🔍</span><strong>Extração</strong><span>inventário de inputs/outputs de cada projeto</span></div>
          <span className="guia-arrow">→</span>
          <div className="guia-step"><span className="guia-step-ico">🔗</span><strong>Cruzamentos</strong><span>catálogo BigQuery + linhagem EGP→EGP</span></div>
          <span className="guia-arrow">→</span>
          <div className="guia-step"><span className="guia-step-ico">📈</span><strong>Painel</strong><span>funis, prontidão e plano de meses</span></div>
        </div>
        <p className="hint">
          As edições dos analistas (status, responsáveis, observações) ficam <em>por cima</em> do dado
          detectado e são <strong>preservadas</strong> quando o corpus é reprocessado.
          {" "}Qualquer usuário logado pode editar; a aba <strong>Gestão</strong> e
          o 📌 da Priorização são restritos ao grupo de gestão (bv_users).
        </p>
      </section>

      <section className="guia-sec">
        <h3>Conceitos que aparecem em todas as abas</h3>
        <div className="guia-terms">
          {CONCEITOS.map((c) => (
            <div className="guia-term" key={c.t}>
              <strong>{c.t}</strong>
              <span>{c.d}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="guia-sec">
        <h3>As abas</h3>
        <div className="guia-cards">
          {ABAS.map((a) => (
            <div className="guia-card" key={a.id}>
              <div className="guia-card-head">
                <span className="guia-card-title">{a.icon} {a.label}</span>
                {a.gestao && <span className="pill todo" title="Restrita ao grupo bv_users">só gestão</span>}
                {(!a.gestao || isGestao) && (
                  <button className="guia-open" onClick={() => onNav(a.id)}>abrir →</button>
                )}
              </div>
              <p>{a.desc}</p>
              <p className="guia-edita">
                {a.edita ? <>✏️ Editável: {a.edita}</> : <>👁 Somente leitura</>}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="guia-sec">
        <h3>Fluxos do dia a dia</h3>
        <table className="guia-table">
          <thead><tr><th>Quero…</th><th>Onde / como</th></tr></thead>
          <tbody>
            {FLUXOS.map((f) => (
              <tr key={f.quero}><td>{f.quero}</td><td>{f.onde}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="guia-sec">
        <h3>Perguntas frequentes</h3>
        {FAQ.map((f) => (
          <details className="guia-faq" key={f.q}>
            <summary>{f.q}</summary>
            <p>{f.a}</p>
          </details>
        ))}
      </section>
      </div>
      <OrganogramaSection />
      </div>
    </div>
  );
}
