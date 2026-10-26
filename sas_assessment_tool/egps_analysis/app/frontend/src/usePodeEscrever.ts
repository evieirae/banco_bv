import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { podeEscrever } from "./escrita";

// Uma regra para a tela inteira: o componente que tem controle de escrita pergunta aqui.
// Lê as mesmas queryKeys (["config"], ["me"]) que o App semeia, sem requisição a mais.
export function usePodeEscrever(): boolean {
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  return podeEscrever(cfg.data, me.data, me.isError);
}
