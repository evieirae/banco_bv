# EGPs Atualizados: isolamento é de escrita, não de leitura

Status: accepted (2026-09-10)

A aba "EGPs Atualizados" do app `monitoramento-sas` foi pedida como "totalmente separada" do app atual — tabelas próprias (`sas_egp_atualizados`, `_inputs`, `_outputs`, criadas fora do `publish_to_databricks.py` e nunca dropadas por ele), endpoints próprios e carga exclusivamente por script local. Decidimos, porém, que a separação vale **só para escrita**: a disponibilidade dos inputs de uma versão recebida é calculada **ao vivo**, por JOIN read-only com `sas_inputs_monitor`, porque o objetivo declarado da aba é evoluir para a troca de versão no escopo — indicadores congelados na data da carga divergiriam do corpus justamente quando a comparação mais importa. A alternativa rejeitada foi o snapshot puro (isolamento total de leitura), que era mais simples e auditável, mas tornaria a fase 2 (juntar ao escopo) uma re-modelagem. A situação congelada na carga (`situacao_no_recebimento`) permanece como fallback para inputs fora do corpus e como registro auditável de "como estava no recebimento".

> Adendo (2026-09-28, ticket 11): a **aba dedicada foi aposentada** (spec §5) — a decisão
> deste ADR **continua valendo**, e ficou mais estrita. O funil próprio por versão
> (`sas_egp_atualizados_pipeline`/`_audit`), única escrita que o backend do módulo tinha,
> saiu junto com a tela: o sucessor usa `sas_egp_pipeline`, como qualquer EGP do corpus.
> As 5 tabelas e o script local `publish_egps_atualizados.py` permanecem; o módulo
> `backend/egps_atualizados.py` é agora read-only **puro** e serve a comparação com o
> antecessor, exibida no detalhe do EGP.

Consequências: o backend do módulo lê tabelas do app atual (nunca escreve — a única exceção prevista é a ação de troca de versão da fase 2, restrita a `bv_admins`); a chave canônica dos inputs da carga local deve seguir exatamente a regra do pipeline atual, senão o JOIN vivo silenciosamente não casa e tudo aparece como "fora do corpus".
