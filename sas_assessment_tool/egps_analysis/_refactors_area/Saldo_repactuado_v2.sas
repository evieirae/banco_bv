LIBNAME B_GERAL '/riscosbv/cobranca/malmeida';

%macro tp_repac (anomes, dt_inicio, dt_fim, fim_mes_m0);

PROC SQL;
CONNECT TO BIGQUERY AS PERM (
    project='bv-sadi-dtm'
    credfile='/projetos/acessos/bq/di/sadi-dtm.json'
    schema='bv-pdbd-prd'
    READ_MODE=storage
    MAX_CHAR_LEN=15
);

CREATE TABLE TP_REPAC_&anomes. AS
SELECT
    &ANOMES. AS SAFRA
 ,A.*
    ,DU.DU
    ,C.STATUS
    ,B.nudiasatraso

    ,CASE
        WHEN B.nudiasatraso <= 0   THEN '0000_0000'
        WHEN B.nudiasatraso <= 4   THEN '0001_0004'
        WHEN B.nudiasatraso <= 15  THEN '0005_0015'
        WHEN B.nudiasatraso <= 30  THEN '0016_0030'
        WHEN B.nudiasatraso <= 60  THEN '0031_0060'
        WHEN B.nudiasatraso <= 90  THEN '0061_0090'
        WHEN B.nudiasatraso <= 120 THEN '0091_0120'
        WHEN B.nudiasatraso <= 150 THEN '0121_0150'
        WHEN B.nudiasatraso <= 180 THEN '0151_0180'
        WHEN B.nudiasatraso <= 720 THEN '0181_0720'
        ELSE '0720_9999'
    END AS FX_ATRASO

    ,C.PRODUTO

    ,CASE 
        WHEN A.FlRestruturacaoContrato = 'S'  THEN 'REESTRUTURACAO'
        WHEN NUDIASATRASO <= 30             THEN 'REORGANIZACAO'
        ELSE 'RENEGOCIACAO'
    END AS TP_REPAC

    ,C.SALDO_M0

FROM CONNECTION TO PERM (

    SELECT DISTINCT
        NuContratoGestao,
        MAX(SqContratoFinanceiro)                   AS SqContratoFinanceiro,
        NuContratoGestaoNovo,
        MAX(sqcontratofinanceironovo)              AS sqcontratofinanceironovo,
        MAX(DATE(dt_baixa))                              AS dt_baixa,
        MAX(dt_reneg)                              AS dt_reneg,
        MAX(SAFE_CAST(vr_presente AS FLOAT64))     AS vr_presente,
        MAX(SAFE_CAST(vr_financiado AS FLOAT64))   AS vr_financiado,
        MAX(SAFE_CAST(Tx_Pactuada AS FLOAT64))     AS Tx_Pactuada,
        MAX(SAFE_CAST(tx_contrato AS FLOAT64))     AS tx_contrato,
        MAX(qt_parcela)                            AS qt_parcela,
        MAX(vr_prestacao)                          AS vr_prestacao,
        MAX(FlRestruturacaoContrato)               AS FlRestruturacaoContrato

    FROM bv-pdbd-prd.trusted_dbreneg.tb_reneg_simulador

    WHERE dt_baixa >= &dt_inicio. 
      AND dt_baixa < &dt_fim.
      AND (dt_cancelamento IS NULL OR dt_reativacao IS NOT NULL)
      AND ST_RENEG = 3

    GROUP BY
        NuContratoGestao,
        NuContratoGestaoNovo
) AS A

LEFT JOIN CONNECTION TO PERM (

    SELECT DISTINCT 
        A.nucontratogestao,
        A.sqcontratofinanceiro,
        A.dt_baixa,
        MIN(B.dt_vencimento) AS dt_vencimento,
        MAX(DATE_DIFF(A.dt_baixa, B.dt_vencimento, DAY)) AS nudiasatraso

    FROM (
        SELECT DISTINCT
            nucontratogestao,
            sqcontratofinanceiro,
            MAX(DATE(dt_baixa)) AS dt_baixa,
            MAX(DATE(dt_reneg)) AS dt_reneg
        FROM bv-pdbd-prd.trusted_dbreneg.tb_reneg_simulador
        WHERE dt_baixa >= &dt_inicio. 
          AND dt_baixa < &dt_fim.
          AND (dt_cancelamento IS NULL OR dt_reativacao IS NOT NULL)
          AND st_reneg = 3
        GROUP BY 1,2
    ) A

    LEFT JOIN (
        SELECT DISTINCT
            cd_contrato,
            sq_contrato_financeiro,
            st_parcela,
            DATE(dt_ultimo_recebimento) AS dt_ultimo_recebimento,
            DATE(dt_vencimento) AS dt_vencimento
        FROM bv-pdbd-prd.dvry_core.tbparcela
    ) B
    ON B.cd_contrato = A.nucontratogestao
   AND B.sq_contrato_financeiro = A.sqcontratofinanceiro

    WHERE B.st_parcela = 'A' 
       OR (B.st_parcela = 'Q' AND DATE(B.dt_ultimo_recebimento) >= DATE(A.dt_baixa))

    GROUP BY 1,2,3

) AS B
ON A.nucontratogestao = B.nucontratogestao
AND A.sqcontratofinanceiro = B.sqcontratofinanceiro

LEFT JOIN CONNECTION TO PERM (

    SELECT
        A.DTPROCESSAMENTO AS DATA_BASE,
        A.NUCONTRATO,
        C.cd_cpf_cnpj,
        C.dt_contrato,
        A.SQCONTRATOFINANCEIRO,

        CASE 
            WHEN A.CdSItuacaoContabil = '1' THEN 'ATIVA'
            WHEN A.CdSItuacaoContabil = '2' THEN 'WO'
            ELSE ''
        END AS STATUS,

        'GCON' AS BASE,
        C.cd_produto,
        D.cdsubproduto,
        C.cd_modalidade_produto,
        I.nmmodalidadeproduto,
        H.NMGRUPOSUBPRODUTO,
        J.FlRestruturacaoContrato,

  CASE
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto IS NULL                           THEN 'CP_BV'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto IN ( '21', '22', '29', '44' )                               THEN 'CP_BV'                 
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 18                              THEN 'CP_BV_MAR_ABERTO'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 22                              THEN 'CP_BV'                    
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 56                              THEN 'CP_PRE_APROVADO' 
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 67                              THEN 'CP_GUIA_BOLSO'                              
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 71                              THEN 'CP_BOM_PRA_CREDITO'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 72                              THEN 'CP_SERASA_ECRED'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 73                              THEN 'CP_FINANZERO'                                               
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 77                              THEN 'CP_MINHA_BV'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 82                              THEN 'CP_EASYCREDITO'                                                            
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto IN (85,86)                        THEN 'CP_NEON'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 87                              THEN 'CP_JUST'                                                                                              
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 97                              THEN 'CP_BANCO_DIGITAL'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 101                             THEN 'CP_BANCO_DIGITAL'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 89                              THEN 'CP_JUROS_BAIXO'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 93                              THEN 'CP_QUERO_FINANCIAR'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 68                              THEN 'CP_GUIA_BOLSO'                                                                         
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 96                              THEN 'CP_ABASTECE_AI'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '19' AND D.cdsubproduto = 100                             THEN 'CP_SAQUE_ANIVERSARIO_FGTS'
   WHEN C.cd_produto = '10' AND C.cd_modalidade_produto = '77' AND (D.cdsubproduto = 100 OR D.cdsubproduto IS NULL) THEN 'CP_SAQUE_ANIVERSARIO_FGTS'                                   
   WHEN C.cd_produto = '11' AND C.cd_modalidade_produto = '16'                                                      THEN 'INSS'
   WHEN C.cd_produto = '11' AND C.cd_modalidade_produto IN ('17', '75')                                             THEN 'PRIVADO'
   WHEN C.cd_produto = '11' AND C.cd_modalidade_produto IN ('18', '32', '37', '39')                                 THEN 'PUBLICO'           
   WHEN C.cd_produto = '14'          AND H.CDGRUPOSUBPRODUTO IN (4, 7)                    THEN 'LEVES'
   WHEN C.cd_produto = '14'          AND H.CDGRUPOSUBPRODUTO IS NULL                      THEN 'LEVES'                  
   WHEN C.cd_produto = '14'          AND H.CDGRUPOSUBPRODUTO = 6                          THEN 'PESADOS'
   WHEN C.cd_produto = '13'          AND D.cdsubproduto IN (15, 21, 75)                   THEN 'CDC_ECOMMERCE'
   WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '12' AND D.cdsubproduto IS NULL                           THEN 'CDC_ECOMMERCE'
   WHEN C.cd_produto = '13'          AND D.cdsubproduto = 76                              THEN 'CDC_TURISMO'
   WHEN C.cd_produto = '13'          AND D.cdsubproduto = 74                              THEN 'CDC_SAUDE'
   WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '51' AND D.cdsubproduto IS NULL                      THEN 'CDC_SAUDE'
   WHEN C.cd_produto = '13'          AND D.cdsubproduto IN ( 46, 47 )                     THEN 'CDC_MOVEIS'
   WHEN C.cd_produto = '13'          AND D.cdsubproduto = 70                              THEN 'CDC_SOLAR'       
   WHEN C.cd_produto = '13'          AND D.cdsubproduto = 53                              THEN 'CDC_ODONTOLOGICO'
   WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '55' AND D.cdsubproduto IS NULL                           THEN 'CDC_SOLAR'
   WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '10' AND D.cdsubproduto IS NULL                           THEN 'CDC_DESCONTO_CHEQUE'                                                
   WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '11' AND D.cdsubproduto IS NULL                           THEN 'CDC_INFORMATICA'
    WHEN C.cd_produto = '13' AND C.cd_modalidade_produto = '62' AND D.cdsubproduto IS NULL                           THEN 'CDC_ESTUDANTIL'       
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '3'  AND D.cdsubproduto IS NULL                           THEN 'CVG_LEVES'  
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '6'  AND D.cdsubproduto IS NULL                           THEN 'CVG_LEVES'       
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '6'  AND D.cdsubproduto = 8                               THEN 'CVG_LEVES'         
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '6'  AND D.cdsubproduto = 13                              THEN 'CVG_PESADOS'        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '27' AND D.cdsubproduto IS NULL                           THEN 'CVG_LEVES'        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '27' AND D.cdsubproduto IN (19,60)                        THEN 'CVG_LEVES'
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '28' AND D.cdsubproduto IN (20,63)                        THEN 'CVG_PESADOS'
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '78' AND D.cdsubproduto IN (13,20)                        THEN 'CVG_PESADOS'
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '79' AND D.cdsubproduto IN (8,19,60)                      THEN 'CVG_LEVES'        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '79' AND D.cdsubproduto IN (13,20)                        THEN 'CVG_PESADOS'        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '2'  AND D.cdsubproduto = 9                               THEN 'LEVES'       
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '3'  AND D.cdsubproduto = 16                              THEN 'LEVES'       
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '3'  AND D.cdsubproduto = 30                              THEN 'PESADOS'
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '5'                                                       THEN 'MOTOS'        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '7'  AND D.cdsubproduto IS NULL                           THEN 'LEVES'          
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '7'  AND D.cdsubproduto = 4                               THEN 'LEVES'         
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '7'  AND D.cdsubproduto = 3                               THEN 'PESADOS'
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '8'  AND D.cdsubproduto IS NULL                           THEN 'LEVES'       
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '8'  AND D.cdsubproduto IN (1,58)                         THEN 'LEVES'          
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '9'  AND D.cdsubproduto IS NULL                           THEN 'PESADOS'                        
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '9'  AND D.cdsubproduto IN ( 2,3,61)                      THEN 'PESADOS'         
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '38' AND D.cdsubproduto = 29                              THEN 'LEVES'                                                 
   WHEN C.cd_produto = '12' AND C.cd_modalidade_produto = '38' AND D.cdsubproduto = 31                              THEN 'PESADOS'
   WHEN C.cd_produto = '16' AND C.cd_modalidade_produto = '60'                                                      THEN 'COBAN'
  END AS PRODUTO,

        MAX(A.NuDiasAtraso) AS ATRASO,

        CASE
            WHEN J.FlRestruturacaoContrato = 'S'
            THEN SUM(CAST(A.vrpermanenciaapropriado AS FLOAT64)
                 + CAST(A.VrTaxaContratoRestruturacao AS FLOAT64))
            ELSE SUM(CAST(A.VrTaxaContrato AS FLOAT64)
                 + CAST(A.VrPermanenciaApropriado AS FLOAT64))
        END AS SALDO_M0

    FROM bv-pdbd-prd.trusted_gestaocontabil.tbcontratocontabil AS A

    LEFT JOIN bv-pdbd-prd.dvry_core.tbcontrato C
        ON A.NUCONTRATO = C.cd_contrato

    LEFT JOIN bv-pdbd-prd.trusted_dbcred.tbproposta AS D
        ON A.NUCONTRATO = D.NUCONTRATOGESTAO
       AND D.STPROPOSTA = 'AP'

    LEFT JOIN bv-pdbd-prd.trusted_dbcred.tbsubprodutogrupo AS G
        ON D.CDSUBPRODUTO = G.CDSUBPRODUTO

    LEFT JOIN bv-pdbd-prd.trusted_dbcred.tbgruposubproduto AS H
        ON G.CDGRUPOSUBPRODUTO = H.CDGRUPOSUBPRODUTO

    LEFT JOIN bv-pdbd-prd.trusted_dbcor.tbmodalidadeproduto AS I
        ON A.cdmodalidadeproduto = I.CDMODALIDADEPRODUTO

    LEFT JOIN bv-pdbd-prd.trusted_dbgestaocdccg.tbcontratofinanceiro AS J
        ON A.NUCONTRATO = J.NUCONTRATO
       AND A.SqContratoFinanceiro = J.SqContratoFinanceiro

    WHERE DATE(A.DTPROCESSAMENTO) = &fim_mes_m0.

    GROUP BY
        DATA_BASE,
        A.NUCONTRATO,
        C.cd_cpf_cnpj,
        C.dt_contrato,
        A.SQCONTRATOFINANCEIRO,
        STATUS,
        BASE,
        C.cd_produto,
        D.cdsubproduto,
        C.cd_modalidade_produto,
        I.nmmodalidadeproduto,
        H.nmgruposubproduto,
        PRODUTO,
        J.FlRestruturacaoContrato

) AS C
ON A.NUCONTRATOGESTAO = C.NUCONTRATO

LEFT JOIN B_GERAL.DIAS_UTEIS AS DU
ON A.dt_baixa = DU.Data

;

QUIT;


%mend;

%tp_repac (202601, '2026-01-01', '2026-02-01', '2025-12-31');
%tp_repac (202602, '2026-02-01', '2026-03-01', '2026-01-31');
%tp_repac (202603, '2026-03-01', '2026-04-01', '2026-02-28');
%tp_repac (202604, '2026-04-01', '2026-05-01', '2026-03-31');
%tp_repac (202605, '2026-05-01', '2026-06-01', '2026-04-30');

DATA TP_REPAC_FINAL;
SET TP_REPAC_202:;
RUN;

PROC SQL;
CREATE TABLE CUBO_TP_REPAC AS
SELECT
    SAFRA
    ,DU
    ,STATUS
    ,FX_ATRASO
    ,PRODUTO
    ,TP_REPAC

    ,SUM(SALDO_M0) AS SALDO_M0
 ,COUNT(NUCONTRATOGESTAO) AS QNT

FROM TP_REPAC_FINAL
GROUP BY
    SAFRA
    ,DU
    ,STATUS
    ,FX_ATRASO
    ,PRODUTO
    ,TP_REPAC
;QUIT;