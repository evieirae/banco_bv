import type { AppConfig, Filters, InputsResponse } from "../types";
import { MultiSelect } from "./MultiSelect";

// Deriva do valor CAPTURADO NO RENDER (onChange é patch, não updater funcional) — por isso
// cada MultiSelect passa onSelectAll: marcar opção a opção faria N patches partindo todos do
// mesmo `filters` velho, e só o último sobreviveria (bug do "selecionar todos", fix 2026-09).
const toggleArr = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

interface Props {
  cfg: AppConfig | null;
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  result: InputsResponse | null;
  loading: boolean;
  onExport?: () => void;
  // Áreas realmente presentes no recorte atual (calculadas no MonitorView). Ausente = lista
  // canônica de cfg.areas.
  areaOptions?: string[];
  responsavelOptions?: string[];
  responsavelLabels?: Record<string, string>;
  mesOptions?: string[];
  mesLabels?: Record<string, string>;
  // recolhimento do cabeçalho (métricas) — ver useHeaderCollapse
  headerCollapsed?: boolean;
  onToggleHeader?: () => void;
}

export function FilterBar({ cfg, filters, onChange, result, loading, onExport, areaOptions, responsavelOptions, responsavelLabels, mesOptions, mesLabels, headerCollapsed, onToggleHeader }: Props) {
  return (
    <section className="filters">
      <div className="seg">
        <button
          className={filters.scope === "indi" ? "on" : ""}
          onClick={() => onChange({ scope: "indi", semExtras: false })}
        >
          Indicium
        </button>
        <button
          className={filters.scope === "indi_deps" && filters.semExtras ? "on" : ""}
          onClick={() => onChange({ scope: "indi_deps", semExtras: true })}
          title="Escopo Indicium + dependências transitivas (todos os níveis). A área selecionada define a base; as dependências entram mesmo de outras áreas. SEM os inputs que só os EGPs extras leem — o que é compartilhado com a linha de base fica, porque esse trabalho existe com ou sem a versão nova."
        >
          Indicium + Dependências
        </button>
        {/* Degrau de cima da escada: mesmo recorte servido pelo backend, agora com os
            inputs exclusivos dos extras. É o PADRÃO da aba — o degrau do meio é que é a
            novidade, e deixá-lo como padrão mudaria o que a aba sempre mostrou. */}
        <button
          className={filters.scope === "indi_deps" && !filters.semExtras ? "on" : ""}
          onClick={() => onChange({ scope: "indi_deps", semExtras: false })}
          title="O anterior MAIS os inputs que só os EGPs extras leem (versão nova enviada pelo BV, casca ou EGP novo). É o recorte completo da aba e o padrão dela."
        >
          + Extras
        </button>
        <button
          className={filters.scope === "base" ? "on" : ""}
          onClick={() => onChange({ scope: "base", semExtras: false })}
        >
          Base completa
        </button>
      </div>

      <MultiSelect label="Categoria" options={cfg?.categorias ?? []}
        sel={new Set(filters.categoria)}
        onToggle={(v) => onChange({ categoria: toggleArr(filters.categoria, v) })}
        onSelectAll={(opts) => onChange({ categoria: opts })}
        onClear={() => onChange({ categoria: [] })} />

      <MultiSelect label="Origem" options={cfg?.origens ?? []}
        sel={new Set(filters.origem)}
        onToggle={(v) => onChange({ origem: toggleArr(filters.origem, v) })}
        onSelectAll={(opts) => onChange({ origem: opts })}
        onClear={() => onChange({ origem: [] })}
        title={"Origem do dado. 'SAS/Local (externo)' = sem produtor conhecido no "
          + "corpus extraído — pode ser ingestão real OU dependência de um EGP não "
          + "recebido. 'SAS/Local (dependência)' = é output de algum EGP do corpus."} />

      <MultiSelect label="Etapa" options={cfg?.etapa_options ?? []}
        sel={new Set(filters.etapa)}
        onToggle={(v) => onChange({ etapa: toggleArr(filters.etapa, v) })}
        onSelectAll={(opts) => onChange({ etapa: opts })}
        onClear={() => onChange({ etapa: [] })} />

      <MultiSelect label="Status" options={cfg?.status_options ?? []}
        sel={new Set(filters.status)}
        onToggle={(v) => onChange({ status: toggleArr(filters.status, v) })}
        onSelectAll={(opts) => onChange({ status: opts })}
        onClear={() => onChange({ status: [] })} />

      <MultiSelect label="Área" options={areaOptions ?? cfg?.areas ?? []}
        title="Só as áreas com input no recorte atual (escopo + demais filtros). Área já selecionada continua na lista mesmo se zerar."
        sel={new Set(filters.area)}
        onToggle={(v) => onChange({ area: toggleArr(filters.area, v) })}
        onSelectAll={(opts) => onChange({ area: opts })}
        onClear={() => onChange({ area: [] })} />

      <MultiSelect label="Responsável" options={responsavelOptions ?? []} labels={responsavelLabels}
        title="Responsável pela ingestão do input (o mesmo da coluna Responsável da tabela)."
        sel={new Set(filters.responsavel ?? [])}
        onToggle={(v) => onChange({ responsavel: toggleArr(filters.responsavel ?? [], v) })}
        onSelectAll={(opts) => onChange({ responsavel: opts })}
        onClear={() => onChange({ responsavel: [] })} />

      {mesOptions && mesOptions.length > 0 && (
        <MultiSelect label="Mês" options={mesOptions} labels={mesLabels}
          sel={new Set(filters.mes)}
          onToggle={(v) => onChange({ mes: toggleArr(filters.mes, v) })}
          onSelectAll={(opts) => onChange({ mes: opts })}
          onClear={() => onChange({ mes: [] })}
          title="Mês do plano de priorização. Um input entra se algum EGP relacionado a ele cai no mês." />
      )}

      <input
        type="search"
        placeholder="buscar em toda a tabela…"
        title={"Busca em TODAS as linhas (no servidor) por nome, categoria, origem, "
          + "área, fontes, path físico e status. Várias palavras: todas precisam "
          + "aparecer na linha. (O Ctrl+F do navegador só acha as linhas visíveis.)"}
        value={filters.q}
        onChange={(e) => onChange({ q: e.target.value })}
      />

      <label className="chk" title="Mostra só o que ainda falta fazer: oculta inputs já modernizados (etapa efetiva Modernizado, incl. detecção automática), sanitizados e ex-dependências">
        <input
          type="checkbox"
          checked={filters.pendentes}
          onChange={(e) => onChange({ pendentes: e.target.checked })}
        />
        só pendentes
      </label>

      <label className="chk" title="Mostra só inputs que são safra: tabelas com data no nome que têm irmãs (a mesma tabela lógica repetida por mês/dia). Com a contagem por família ligada, cada linha é a família inteira; sem ela, cada safra aparece em sua linha. Quem decide é o backend, sobre a base completa — uma safra sozinha no recorte continua sendo safra.">
        <input
          type="checkbox"
          checked={filters.safra}
          onChange={(e) => onChange({ safra: e.target.checked })}
        />
        só safras
      </label>

      <label className="chk" title="Inputs com Status Auto divergindo em relação ao Status Humano">
        <input
          type="checkbox"
          checked={filters.divergence}
          onChange={(e) => onChange({ divergence: e.target.checked })}
        />
        status divergente
      </label>

      <label className="chk" title="Inputs cujos produtores não estão identificados na base de dados completa (extrações de metadados dos EGPs)">
        <input
          type="checkbox"
          checked={filters.bloqueador}
          onChange={(e) => onChange({ bloqueador: e.target.checked })}
        />
        sem produtor definido
      </label>

      <label className="chk" title="Mostra só os inputs que algum EGP extra lê — extra = EGP com vínculo de atualização (versão nova enviada pelo BV) ou casca, fora da linha de base congelada. Inclui os inputs que a linha de base também lê: a pergunta aqui é o que a versão nova consome. O card 'Inputs dos extras' da Visão geral conta um conjunto menor, só os que NENHUM EGP contável lê — os dois números não batem de propósito.">
        <input
          type="checkbox"
          checked={filters.extra}
          onChange={(e) => onChange({ extra: e.target.checked })}
        />
        só inputs de extras
      </label>

      {filters.scope === "indi_deps" && (
        <label className="chk" title="Inclui na tabela e no export os inputs consumidos APENAS por ex-dependências (EGPs que saíram do recorte Indicium + deps). Ficam em cinza e nunca contam nos cards — útil p/ analisar o que já mudou/saiu sem ir ao banco.">
          <input
            type="checkbox"
            checked={filters.exDeps}
            onChange={(e) => onChange({ exDeps: e.target.checked })}
          />
          mostrar ex-dependências
        </label>
      )}

      <div className="count">
        {loading ? "carregando…" : result ? `${result.total.toLocaleString("pt-BR")} linhas` : ""}
        {result?.capped ? " (mostrando primeiras 20k)" : ""}
      </div>

      {onExport && (
        <button className="ghost csv-btn" onClick={onExport} disabled={loading || !result?.total}
          title="Baixar CSV com as linhas exibidas (filtros + busca aplicados)">
          ⬇ Exportar CSV
        </button>
      )}
      {onToggleHeader && (
        <button className="hdr-toggle" onClick={onToggleHeader}
          aria-label={headerCollapsed ? "Expandir o cabeçalho" : "Recolher o cabeçalho"}
          title={headerCollapsed
            ? "Expandir o cabeçalho (métricas)"
            : "Recolher o cabeçalho — mais tabela na tela (persistente)"}>
          {headerCollapsed ? "▾" : "▴"}
        </button>
      )}
    </section>
  );
}
