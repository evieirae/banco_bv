import { useRef, useState, type UIEvent } from "react";

// Recolhimento do cabeçalho das abas de tabela (métricas + chips) — pedido 2026-08-28.
// Duas camadas que compõem o estado efetivo (`collapsed = pref || auto`):
//   - preferência PERSISTENTE: botão ▴/▾, salvo em localStorage por aba;
//   - recolhimento AUTOMÁTICO transitório: rolar a tabela p/ baixo recolhe, rolar p/
//     cima (ou voltar ao topo) expande de volta — só quando a preferência é "expandido".
// Expandir manualmente zera o auto (a intenção do usuário vence o scroll).
//
// `auto: false` DESLIGA a segunda camada: com poucas linhas, o corpo da tabela mal rola, e
// o recolher/expandir dispara com qualquer tremida do trackpad — o cabeçalho pisca e as
// métricas somem debaixo do cursor. O botão ▴/▾ continua funcionando; o que sai é só o
// gatilho por scroll. Desligado na aba EGPs em 08/10/2026 e na aba Inputs em 09/10 — os
// dois únicos usos do hook, então hoje a camada automática não roda em lugar nenhum.
export function useHeaderCollapse(storageKey: string, { auto: autoOn = true } = {}) {
  const [pref, setPref] = useState(() => {
    try { return localStorage.getItem(storageKey) === "1"; } catch { return false; }
  });
  const [auto, setAuto] = useState(false);
  const lastY = useRef(0);
  const collapsed = pref || auto;
  const toggle = () => {
    setPref((p) => {
      const n = !p;
      try { localStorage.setItem(storageKey, n ? "1" : "0"); } catch { /* sem storage */ }
      return n;
    });
    setAuto(false);
  };
  const onScroll = (e: UIEvent<HTMLElement>) => {
    if (!autoOn) return;
    const y = e.currentTarget.scrollTop;
    const dy = y - lastY.current;
    lastY.current = y;
    if (y > 120 && dy > 4) setAuto(true);
    else if (y <= 40 || dy < -16) setAuto(false);
  };
  return { collapsed, toggle, onScroll };
}
