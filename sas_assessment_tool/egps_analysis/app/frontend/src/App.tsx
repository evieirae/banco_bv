import { lazy, Suspense, useEffect, useState, type MouseEvent } from "react";
import { api } from "./api";
import type { AppConfig } from "./types";
import { MonitorView } from "./components/MonitorView";
import { OutputsView } from "./components/OutputsView";
import { ReadinessView } from "./components/ReadinessView";
import { IndiciumView } from "./components/IndiciumView";
import { WavesView } from "./components/WavesView";
import { HistoryView } from "./components/HistoryView";
import { ResumoView } from "./components/ResumoView";
import { GuiaView } from "./components/GuiaView";
import { GestaoView } from "./components/GestaoView";
import { AcompanhamentoView } from "./components/AcompanhamentoView";
import { TempoEtapasView } from "./components/TempoEtapasView";
import { GenieView } from "./components/GenieView";
import SincronizacaoBanner from "./components/SincronizacaoBanner";
import { resolveInitialTheme, applyTheme, readStoredTheme, type Theme } from "./theme";
import { QueryClient, QueryClientProvider, useIsFetching, useQueryClient } from "@tanstack/react-query";
import { type View, TABS, parsePath, pathFor } from "./routes";
import { prefetchAllTabs } from "./prefetch";

// Linhagem sob demanda: é a única view que puxa cytoscape (+fcose/expand-collapse), ~metade
// do bundle — e a aba está dormente (fora de TABS, ver routes.ts). Lazy tira o grafo do
// chunk principal sem apagar a view; export nomeado => o `.then` monta o `default`.
const LineageView = lazy(() => import("./components/LineageView").then((m) => ({ default: m.LineageView })));

// Cache compartilhado de "server state": persiste entre trocas de aba (sem flicker)
// e é invalidado a cada PATCH para propagar a edição às demais superfícies.
// staleTime alto (5 min): dados de baixa frequência de mudança (EGP/Input/Output/etc) são
// servidos do cache ao trocar de aba — sem re-hit no warehouse por navegação. Mutations já
// chamam invalidateQueries explicitamente, então edições próprias propagam na hora
// independentemente do staleTime; o ⟳ "Atualizar dados" força refetch de tudo (mudanças de
// fora / multiusuário). gcTime longo evita cold-load ao voltar a uma aba. refetchOnWindowFocus
// off: o ⟳ é o mecanismo de refresh — foco na janela não deve custar latência surpresa.
// retry: no máximo 1, e nunca em 4xx (403/404/409 são respostas definitivas; `status` vem no
// Error de api.ts/gestaoApi.ts). Cada tentativa é outra ida ao warehouse — o default (3, com
// backoff) rodava 4× um endpoint lento que falhou.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, gcTime: 30 * 60 * 1000, refetchOnWindowFocus: false,
      retry: (falhas, e) => {
        const st = (e as { status?: number }).status;
        return falhas < 1 && !(st != null && st >= 400 && st < 500);
      },
    },
  },
});

// Atualiza dados sob demanda: invalida tudo → a aba ativa rebusca na hora e as
// demais revalidam ao abrir. Cobre mudanças vindas de fora (republish, multiusuário).
function RefreshButton() {
  const qc = useQueryClient();
  const fetching = useIsFetching();
  return (
    <button
      className="theme-btn"
      onClick={() => qc.invalidateQueries()}
      disabled={fetching > 0}
      aria-label="Atualizar dados"
      title="Atualizar dados (puxa mudanças do servidor)"
    >
      {fetching > 0 ? "⏳" : "⟳"}
    </button>
  );
}

// View, TABS e os helpers de rota (parsePath/pathFor/APP_BASE) vivem em ./routes
// para serem compartilhados com o botão "copiar link" do EgpDetailPanel.

export function App() {
  const [view, setView] = useState<View>(() => parsePath(window.location.pathname).view);
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<string | null>(null);
  const [semAcesso, setSemAcesso] = useState(false);
  // EGP a abrir/destacar: vem do cross-nav (Escopo/Monitoramento) ou de um
  // deep-link "/egps/<id>" no carregamento inicial.
  const [egpToOpen, setEgpToOpen] = useState<string | null>(() => parsePath(window.location.pathname).egp);
  const [theme, setTheme] = useState<Theme>(
    () =>
      (document.documentElement.getAttribute("data-theme") as Theme | null) ??
      resolveInitialTheme(
        readStoredTheme(),
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
      // sem escolha manual: aplica no DOM (sem persistir, p/ não travar o auto-follow)
      if (!readStoredTheme()) {
        const next: Theme = e.matches ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        setTheme(next);
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // troca de aba: atualiza estado + URL (sem recarregar a página). `egp` opcional
  // monta o deep-link "/egps/<id>" (cross-nav já deixa a URL compartilhável).
  function go(next: View, egp: string | null = null) {
    setView(next);
    const path = pathFor(next, egp);
    if (window.location.pathname !== path) {
      window.history.pushState(null, "", path);
    }
  }

  // clique simples navega in-place; ctrl/⌘/shift/alt+clique (ou botão do meio)
  // caem no comportamento padrão do <a>: abrir em nova guia/janela.
  function onTabClick(e: MouseEvent<HTMLAnchorElement>, next: View) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go(next);
  }

  // botões voltar/avançar do navegador
  useEffect(() => {
    function onPop() {
      const r = parsePath(window.location.pathname);
      setView(r.view);
      setEgpToOpen(r.egp);
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // normaliza a URL inicial (ex. "/" ou caminho desconhecido -> "/monitoramento")
  useEffect(() => {
    const r = parsePath(window.location.pathname);
    const path = pathFor(r.view, r.egp);
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
  }, []);

  useEffect(() => {
    // Semeia o cache: usePodeEscrever (controles de escrita) lê ["config"] e ["me"] sem
    // fazer a mesma requisição de novo.
    api.config().then((c) => { queryClient.setQueryData(["config"], c); setCfg(c); })
      .catch((e: { status?: number }) => {
        if (e?.status === 403) setSemAcesso(true);
      });
    api.me().then((r) => { queryClient.setQueryData(["me"], r); setUser(r.user); }).catch(() => {});
  }, []);

  // Prefetch das demais abas: aquece o cache em background quando cfg chega (precisa do
  // is_gestao p/ decidir as abas restritas) E a aba visível ASSENTOU (nenhuma query buscando).
  // Antes rodava no idle após o 1º paint — que, com a main thread ociosa esperando rede, era
  // praticamente junto com a 1ª carga: ~20 requests disputando o warehouse com a aba que o
  // usuário está olhando. Teto de 30s: uma query pendurada não adia o aquecimento p/ sempre.
  // Roda uma vez.
  useEffect(() => {
    if (!cfg) return;
    let feito = false;
    const run = () => {
      if (feito) return;
      feito = true;
      unsub();
      window.clearTimeout(teto);
      prefetchAllTabs(queryClient, cfg);
    };
    const unsub = queryClient.getQueryCache().subscribe(() => {
      if (queryClient.isFetching() === 0) run();
    });
    const teto = window.setTimeout(run, 30_000);
    if (queryClient.isFetching() === 0) run();
    return () => { feito = true; unsub(); window.clearTimeout(teto); };
  }, [cfg]);

  if (semAcesso) {
    return (
      <div className="sem-acesso">
        <h1>Painel de Modernização SAS</h1>
        <p>Seu e-mail não tem acesso a este app. Peça à gestão do projeto para cadastrá-lo.</p>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
    <div className={view === "resumo" || view === "guia" ? "app app-doc" : "app"}>
      <header className="topbar">
        <div>
          <h1>Painel de Modernização SAS</h1>
          <span className="sub">{cfg?.scope ?? "…"}</span>
        </div>
        <nav className="tabs">
          {TABS.filter((t) => t.id === "genie"
            ? !!(cfg?.is_gestao && cfg?.genie_embed_url)
            : (t.id !== "gestao" && t.id !== "tempoetapas") || cfg?.is_gestao).map((t) => (
            <a
              key={t.id}
              href={pathFor(t.id)}
              className={view === t.id ? "on" : ""}
              onClick={(e) => onTabClick(e, t.id)}
            >
              {t.label}
            </a>
          ))}
        </nav>
        <div className="who">
          <RefreshButton />
          <button className="theme-btn" onClick={toggleTheme} aria-label="Alternar tema" title="Tema claro/escuro">
            {theme === "dark" ? "☀" : "🌙"}
          </button>
          {user ? `👤 ${user}` : ""}
        </div>
      </header>
      {cfg?.sincronizado_em && <SincronizacaoBanner em={cfg.sincronizado_em} />}

      {view === "resumo" && <ResumoView cfg={cfg} onNav={go} />}
      {view === "monitor" && (
        <MonitorView cfg={cfg}
          onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }}
          inputToOpen={egpToOpen}
          onInputOpened={() => setEgpToOpen(null)}
          onInputRoute={(c) => {
            const path = pathFor("monitor", c);
            if (window.location.pathname !== path) window.history.pushState(null, "", path);
          }} />
      )}
      {view === "outputs" && <OutputsView cfg={cfg} onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }} />}
      {view === "readiness" && (
        <ReadinessView cfg={cfg} egpToOpen={egpToOpen} onEgpOpened={() => setEgpToOpen(null)}
          onOpenInput={(c) => { setEgpToOpen(c); go("monitor", c); }} />
      )}
      {view === "indicium" && <IndiciumView onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }} />}
      {view === "waves" && <WavesView cfg={cfg} onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }} />}
      {view === "lineage" && (
        <Suspense fallback={<div className="empty">carregando…</div>}><LineageView /></Suspense>
      )}
      {view === "history" && (
        <HistoryView onOpenEgp={(p) => { setEgpToOpen(p); go("readiness", p); }}
          onOpenInput={(c) => { setEgpToOpen(c); go("monitor", c); }} />
      )}
      {view === "acompanhamento" && <AcompanhamentoView />}
      {view === "guia" && <GuiaView isGestao={!!cfg?.is_gestao} onNav={go} />}
      {view === "gestao" && (cfg?.is_gestao
        ? <GestaoView />
        : cfg ? <div className="empty">Acesso restrito ao grupo de gestão (bv_users).</div> : null)}
      {view === "tempoetapas" && (cfg?.is_gestao
        ? <TempoEtapasView cfg={cfg} />
        : cfg ? <div className="empty">Acesso restrito ao grupo de gestão (bv_users).</div> : null)}
      {view === "genie" && (cfg?.is_gestao && cfg.genie_embed_url
        ? <GenieView url={cfg.genie_embed_url} />
        : cfg ? <div className="empty">Acesso restrito ao grupo de gestão (bv_users).</div> : null)}
    </div>
    </QueryClientProvider>
  );
}
