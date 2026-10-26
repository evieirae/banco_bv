/* ======================================================== */
/* ================ Libname e Parametros Final ================== */
/* ======================================================== */

option compress = binary;
%include '/projetos/MISV/sas-misv-base-lib/scripts/ConectaDB.sas';
%include '/projetos/MISV/sas-misv-base-lib/scripts/libname.sas';
%include '/infogrc/utils/all-includes.sas';

proc sql;
CREATE TABLE TbExtProposta as 
SELECT 
	ExtProposta.NuAnoMes
	,COALESCE(Sinergia.CdParceiroComercial,ExtProposta.CdParceiroComercial) as CdParceiroComercial
	,ExtProposta.StProposta
	,ExtProposta.DtEntradaProposta
	,ExtProposta.DtStatusProposta
	,GrupoProdutoMeta.NmGrupoProdutoMeta

FROM bases.TbExtProposta ExtProposta

	LEFT JOIN bases.TbPropostaComplementoParceiro Sinergia 
	 ON ExtProposta.NuProposta = Sinergia.NuProposta

 	LEFT JOIN basegrc.TbGrupoProdutoMeta GrupoProdutoMeta
		ON  ExtProposta.CdGrupoSubProduto = GrupoProdutoMeta.CdGrupoSubProduto

WHERE ExtProposta.FlPropostaValida = 'S' 
AND ExtProposta.NuAnoMes >= 202301

;run;

proc sql; create index CdParceiroComercial on TbExtProposta;run;

proc sql;
create table TbProducaoApartado as 
select 
	CdParceiroComercial
	,case
		when NmGrupoProdutoMeta IN ('CVG Leves','CVG Pesados') then 'CVG'
		when NmGrupoProdutoMeta IN ('Leves','Motos','Pesados') then 'RODAS'
	end as DsAtividadeFinanciamento
	,SUM(VrProducao) as VrProducao
	,SUM(VrMargem) as VrMargem
	,SUM(VpTxGerencial) AS VpTxGerencial
	,SUM(VpSpread) AS VpSpread

from tmp.TbProducao
where NmGrupoProdutoMeta IN ('CVG Leves','CVG Pesados','Leves','Motos','Pesados')
  and DtContrato >= today()-30 
group by 1,2
;run;

proc sql;
create table TbProducaoAcumulado as 
select 
	CdParceiroComercial
	,case
		when NmGrupoProdutoMeta IN ('CVG Leves','CVG Pesados','Leves','Motos','Pesados') then 'RODAS E CVG'
		when NmGrupoProdutoMeta IN ('CP') then 'CREDITO PESSOAL'
	end as DsAtividadeFinanciamento
	,SUM(VrProducao) as VrProducao
	,SUM(VrMargem) as VrMargem
	,SUM(VpTxGerencial) AS VpTxGerencial
	,SUM(VpSpread) AS VpSpread

from tmp.TbProducao
where NmGrupoProdutoMeta IN ('CVG Leves','CVG Pesados','Leves','Motos','Pesados','CP')
  and DtContrato >= today()-30 
group by 1,2
;run;

data TbProducao;
	set TbProducaoAcumulado
		TbProducaoApartado
;run;

proc sql;
CREATE TABLE TbParceiroOriginacaoRodas AS
 SELECT
	 ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,'RODAS' AS DsAtividadeFinanciamento
	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.FlSeguradora
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 	
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1)
	AND ExtProposta.NmGrupoProdutoMeta IN ('Leves','Motos','Pesados')
	AND ParceiroComercial.FlAtivo = 'S'
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17
;run;


proc sql;
CREATE TABLE TbParceiroOriginacaoCVG AS
 SELECT
	 ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,'CVG' AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.FlSeguradora
	,ParceiroComercial.NuCnpjLoja

	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1)
	AND ExtProposta.NmGrupoProdutoMeta IN ('CVG Leves','CVG Pesados')
	AND ParceiroComercial.FlAtivo = 'S'
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17
;run;


proc sql;
CREATE TABLE TbParceiroOriginacao AS
 SELECT
	 ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.FlSeguradora
	,ParceiroComercial.NuCnpjLoja

	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17
;run;

data TbParceiroOriginacaoVeiculos;
	set TbParceiroOriginacao
		TbParceiroOriginacaoRodas
		TbParceiroOriginacaoCVG
;run;


PROC SQL;
CREATE TABLE ParceiroComercial AS 
SELECT 
	TbParceiroComercial.CdParceiroComercial
	,TbParceiroComercial.NuCnpjLoja
	,TbParceiroComercial.NmParceiroComercial
	,TbParceiroComercial.NmGrupoConcessionaria
	,TbParceiroComercial.NmBandeiraGrupoConcessionaria
	,CASE WHEN TbParceiroComercial.PredominanciaProduto = 'Motos' THEN  FlPorteNovoMotos ELSE FlPorteA END as FlPorteA
	,TbParceiroComercial.PredominanciaProduto
	,TbParceiroComercial.DsGrupoParceiroLocadoras AS Locadora
	,TbParceiroComercial.NmAutoShopping
	,NmCidade	
	,CdUf
FROM tmp.TbParceiroComercial TbParceiroComercial
	left join basegrc.TbPortepdv PortePDV
		on TbParceiroComercial.NuCnpjLoja = PortePDV.NuCnpjLoja
		AND PortePDV.NuAno = year(today()) 
WHERE FlAtivo = 'S'
;run;

PROC SQL;
CREATE TABLE TbParceiroOriginacaoVeiculos AS 
SELECT 
	 TbParceiroOriginacaoVeiculos.CdParceiroComercial
	,TbParceiroOriginacaoVeiculos.NmParceiroComercial
	,TbParceiroOriginacaoVeiculos.DtCadastro
	,TbParceiroOriginacaoVeiculos.TpAtividade
	,TbParceiroOriginacaoVeiculos.DsAtividadeFinanciamento
	,TbParceiroOriginacaoVeiculos.NmTipoParceiroComercial
	,ParceiroComercial.NmCidade	AS NmCidadeParceiro
	,ParceiroComercial.CdUf AS UFParceiro
	,TbParceiroOriginacaoVeiculos.NmColaboradorC
	,TbParceiroOriginacaoVeiculos.NmAreaEstruturaComercialC
	,TbParceiroOriginacaoVeiculos.NmSubEstruturaComercialC
	,TbParceiroOriginacaoVeiculos.NmCanalEstruturaComercialC
	,TbParceiroOriginacaoVeiculos.CdFilialC
	,TbParceiroOriginacaoVeiculos.DsLoginN1C
	,TbParceiroOriginacaoVeiculos.DsLoginN2C
	,TbParceiroOriginacaoVeiculos.DsLoginN3C
	,TbParceiroOriginacaoVeiculos.LstSubstituicaoC
	,TbParceiroOriginacaoVeiculos.FlSeguradora
	,TbParceiroOriginacaoVeiculos.NuCnpjLoja
	,TbParceiroOriginacaoVeiculos.DtUltimaOriginacao
	,TbParceiroOriginacaoVeiculos.DtPrimeiraOriginacao
	,TbParceiroOriginacaoVeiculos.DtPrimeiraEfetivacao
	,TbParceiroOriginacaoVeiculos.DtUltimaEfetivacao


FROM TbParceiroOriginacaoVeiculos TbParceiroOriginacaoVeiculos
	LEFT JOIN ParceiroComercial ParceiroComercial
		on TbParceiroOriginacaoVeiculos.CdParceiroComercial = ParceiroComercial.CdParceiroComercial
		
;run;


proc sql;
CREATE TABLE TbVisaoOriginacaoParceiro AS
 SELECT
	ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.DsAtividadeFinanciamento
	,ParceiroOriginacao.NmTipoParceiroComercial
	,ParceiroOriginacao.NmCidadeParceiro
	,ParceiroOriginacao.UFParceiro
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.FlSeguradora
	,ParceiroOriginacao.NuCnpjLoja
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	
	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao

	,CASE 
		WHEN DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'
		WHEN intnx('month',today(),-13,'same') >= DtUltimaOriginacao THEN '+ 12 Meses sem originar' 	
		WHEN intnx('month',today(),-8,'same') >= DtUltimaOriginacao THEN '8 a 12 Meses sem originar'
		WHEN intnx('month',today(),-4,'same') >= DtUltimaOriginacao THEN '4 a 7 Meses sem originar' 
		WHEN intnx('month',today(),-1,'same') >= DtUltimaOriginacao  THEN '1 a 3 meses sem originar'
		WHEN today()-16 >= DtUltimaOriginacao THEN ' 16 a 30d sem originar'
		WHEN DtUltimaOriginacao >= today()-15  THEN ' Originaram nos últimos 15d'
	END AS DsTempoSemOriginacao
	,CASE 
		WHEN DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'
		WHEN intnx('month',today(),-13,'same') >= DtUltimaEfetivacao THEN '+ 12 Meses sem efetivar' 	
		WHEN intnx('month',today(),-8,'same') >= DtUltimaEfetivacao THEN '8 a 12 Meses sem efetivar'
		WHEN intnx('month',today(),-4,'same') >= DtUltimaEfetivacao THEN '4 a 7 Meses sem efetivar' 
		WHEN intnx('month',today(),-1,'same') >= DtUltimaEfetivacao  THEN '1 a 3 meses sem efetivar'
		WHEN today()-16 >= DtUltimaEfetivacao THEN ' 16 a 30d sem efetivar'
		WHEN DtUltimaEfetivacao >= today()-15  THEN ' Efetivaram nos últimos 15d'
	END AS DsTempoSemEfetivacao
	,CASE WHEN DtUltimaOriginacao >= today()-30  THEN ' Originaram nos últimos 30d'	END AS DsOriginacao
	,CASE WHEN DtUltimaEfetivacao >= today()-30  THEN ' Efetivaram nos últimos 30d'	END AS DsEfetivacao
	,SUM(Producao.VrProducao) as VrProducao
	,SUM(Producao.VrMargem) as VrMargem
	,SUM(Producao.VpTxGerencial) AS VpTxGerencial
	,SUM(Producao.VpSpread) AS VpSpread

 FROM TbParceiroOriginacaoVeiculos ParceiroOriginacao

 	LEFT JOIN TbProducao Producao 
		ON ParceiroOriginacao.CdParceiroComercial = Producao.CdParceiroComercial
	   AND ParceiroOriginacao.DsAtividadeFinanciamento = Producao.DsAtividadeFinanciamento
	   
 WHERE  TpAtividade IN (1,5) 
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27
;run;

proc export 
data=TbVisaoOriginacaoParceiro
file='/riscosbvf/BA/processos/output/TbVisaoOriginacaoParceiro.csv' replace
dbms=dlm;
delimiter=';';
run;

X "mv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoOriginacaoParceiro.csv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/processados/ ";



/* ========================================================== */
/* ================ Visao Originacao Solar ================== */
/* ========================================================== */

proc sql;
CREATE TABLE TbParceiroOriginacaoSolar AS
 SELECT
	'TpDadosAtual' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja

	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-1' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 		THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 		THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 		THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja

	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM1.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-2' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM2.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-3' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM3.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-4' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM4.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-5' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM5.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17

UNION ALL

SELECT
	'TpDadosM-6' AS TpDados
	,ParceiroComercial.CdParceiroComercial
	,ParceiroComercial.NmParceiroComercial
	,ParceiroComercial.DtCadastro AS DtCadastro format date9.
	,ParceiroComercial.TpAtividade
	,CASE 
		WHEN ParceiroComercial.TpAtividade = 1 THEN 'RODAS E CVG'
		WHEN ParceiroComercial.TpAtividade = 7 THEN 'NOVOS NEGOCIOS'
		WHEN ParceiroComercial.TpAtividade = 8 THEN 'PRIVADO'
			WHEN ParceiroComercial.TpAtividade = 26 THEN 'IMOBILIARIA'
		ELSE ParceiroComercial.DsAtividadeFinanciamento END AS DsAtividadeFinanciamento

	,case when ParceiroComercial.NmAutoShopping IS NOT NULL then 'Auto Shopping' else ParceiroComercial.NmTipoParceiroComercial end as NmTipoParceiroComercial
	,ParceiroComercial.NmColaboradorC
	,ParceiroComercial.NmAreaEstruturaComercialC
	,ParceiroComercial.NmSubEstruturaComercialC
	,ParceiroComercial.NmCanalEstruturaComercialC
	,ParceiroComercial.CdFilialC
	,ParceiroComercial.DsLoginN1C
	,ParceiroComercial.DsLoginN2C
	,ParceiroComercial.DsLoginN3C
	,ParceiroComercial.LstSubstituicaoC
	,ParceiroComercial.NuCnpjLoja
	
	,MAX(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtUltimaOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta IN ('A','AP','PA','CA','N') THEN ExtProposta.DtEntradaProposta END) AS DtPrimeiraOriginacao format date9.
	,MIN(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtPrimeiraEfetivacao  format date9.
	,MAX(CASE WHEN ExtProposta.StProposta = 'AP' THEN ExtProposta.DtStatusProposta END) AS DtUltimaEfetivacao format date9.

 FROM tmp.TbParceiroComercial ParceiroComercial

		LEFT JOIN TbExtProposta ExtProposta
			ON ParceiroComercial.CdParceiroComercial = ExtProposta.CdParceiroComercial 
	 
 WHERE ParceiroComercial.TpAtividade IS NOT NULL
 	AND ParceiroComercial.TpAtividade IN (1,7,5,8)
	AND ParceiroComercial.FlAtivo = 'S'
	AND NuAnoMes <= &safraM6.
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17
;run;

proc sql;
CREATE TABLE TbVisaoCobansSolarAtual AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN intnx('month',today(),-5,'same') >= DtUltimaOriginacao  THEN '+ 5 Meses sem originar'
		WHEN intnx('month',today(),-3,'same') >= DtUltimaOriginacao   THEN '3 a 4 Meses sem originar' 	
		WHEN intnx('month',today(),-1,'same') >= DtUltimaOriginacao   THEN '1 a 2 Meses sem originar'
/*		WHEN today()-16 >= DtUltimaOriginacao AND TpDados = 'TpDadosAtual' THEN ' 16 a 30d sem originar'*/
		WHEN DtUltimaOriginacao >= today()-30   THEN ' Originaram nos últimos 30d'
		END AS DsTempoSemOriginacao
	,CASE 
		WHEN DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'
		WHEN intnx('month',today(),-5,'same') >= DtUltimaEfetivacao THEN '+ 5 Meses sem efetivar'
		WHEN intnx('month',today(),-3,'same') >= DtUltimaEfetivacao THEN '3 a 4 Meses sem efetivar' 
		WHEN intnx('month',today(),-1,'same') >= DtUltimaEfetivacao  THEN '1 a 2 meses sem efetivar'
/*		WHEN today()-16 >= DtUltimaEfetivacao THEN ' 16 a 30d sem efetivar'*/
		WHEN DtUltimaEfetivacao >= today()-30  THEN ' Efetivaram nos últimos 30d'
		END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'


WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosAtual'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM1 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja	

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-1'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM2 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja	

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-2'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM3 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja	

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-3'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM4 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja	

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-4'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM5 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja		

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-5'

;run;


proc sql;
CREATE TABLE TbVisaoCobansSolarM6 AS
 SELECT
 	ParceiroOriginacao.TpDados
	,ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja	

	,INTCK('day',DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN  DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-5)) THEN '+ 5 Meses sem originar'
		WHEN  DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-3)) THEN '3 a 4 Meses sem originar'
		WHEN DtUltimaOriginacao <= MAX(intnx('month',DtUltimaOriginacao,-1)) THEN '1 a 2 Meses sem originar'
		WHEN DtUltimaOriginacao <= DtUltimaOriginacao THEN 'Originaram nos últimos 30d'
	END AS DsTempoSemOriginacao
	,CASE
		WHEN  DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'	
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-5)) THEN '+ 5 Meses sem efetivar'
		WHEN  DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-3)) THEN '3 a 4 Meses sem efetivar'
		WHEN DtUltimaEfetivacao <= MAX(intnx('month',DtUltimaEfetivacao,-1)) THEN '1 a 2 meses sem efetivar'
		WHEN DtUltimaEfetivacao <= DtUltimaEfetivacao THEN ' Efetivaram nos últimos 30d'
	END AS DsTempoSemEfetivacao

 FROM TbParceiroOriginacaoSolar ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Solar'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'NOVOS NEGOCIOS'

WHERE ParceiroOriginacao.TpAtividade = 7
AND ParceiroOriginacao.TpDados = 'TpDadosM-6'

;run;


DATA TbVisaoCobansSolar;
SET TbVisaoCobansSolarAtual
	TbVisaoCobansSolarM1
	TbVisaoCobansSolarM2
	TbVisaoCobansSolarM3
	TbVisaoCobansSolarM4
	TbVisaoCobansSolarM5
	TbVisaoCobansSolarM6
;RUN;

proc export 
data=TbVisaoCobansSolar
file='/projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoCobansSolar.csv' replace
dbms=dlm;
delimiter=';';
run;

X 'mv /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoCobansSolar.csv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/processados/';


/*proc export */
/*data=TbVisaoCobansSolar*/
/*file='/riscosbvf/BA/processos/tmp/TbVisaoCobansSolar.csv' replace*/
/*file='/riscosbvf/BA/processos/tmp/TbPainelCoban.csv' replace*/
/*dbms=dlm;*/
/*delimiter=';';*/
/*run;*/
/**/
/*X "mv  /riscosbvf/BA/processos/tmp/TbVisaoCobansSolar.csv  /riscosbvf/BA/processos/output/ ";*/

/* ========================================================== */
/* =============== Visao Originacao Privado ================= */
/* ========================================================== */

proc sql;
CREATE TABLE TbVisaoConveniosPrivado AS
 SELECT
	ParceiroOriginacao.CdParceiroComercial
	,ParceiroOriginacao.NmParceiroComercial
	,ParceiroOriginacao.DtCadastro 
	,ParceiroOriginacao.NmColaboradorC
	,ParceiroOriginacao.NmAreaEstruturaComercialC
	,ParceiroOriginacao.NmSubEstruturaComercialC
	,ParceiroOriginacao.NmCanalEstruturaComercialC
	,ParceiroOriginacao.DsLoginN1C
	,ParceiroOriginacao.DsLoginN2C
	,ParceiroOriginacao.DsLoginN3C
	,ColaboradorFocal.LstColaboradorFocal
	,ParceiroComercial.StBloqueioEmpresa
	,ParceiroComercial.CdClassificacaoLimiteConvenio
	,ParceiroComercial.NmClassificacaoLimiteConvenio
	,ParceiroComercial.CdCobanAtendimento
	,ParceiroComercial.NmCobanAtendimento
	,ParceiroOriginacao.LstSubstituicaoC
	,ParceiroOriginacao.DtPrimeiraOriginacao
	,ParceiroOriginacao.DtUltimaOriginacao 
	,ParceiroOriginacao.DtPrimeiraEfetivacao 
	,ParceiroOriginacao.DtUltimaEfetivacao
	,ParceiroOriginacao.NuCnpjLoja		

	,INTCK('day',ParceiroOriginacao.DtCadastro,DtPrimeiraOriginacao) AS QtDiasPrimeiraOriginacao
	,INTCK('day',ParceiroOriginacao.DtCadastro,DtPrimeiraEfetivacao) AS QtDiasPrimeiraEfetivacao
	,CASE
		WHEN StBloqueioEmpresa = 'B' THEN 'Bloqueados'
		WHEN DtUltimaOriginacao IS NULL THEN 'Nunca Originaram'	
		WHEN intnx('month',today(),-5,'same') >= DtUltimaOriginacao THEN '+ 5 Meses sem originar'
		WHEN intnx('month',today(),-3,'same') >= DtUltimaOriginacao THEN '3 a 4 Meses sem originar' 	
		WHEN intnx('month',today(),-1,'same') >= DtUltimaOriginacao  THEN '1 a 2 Meses sem originar'
		WHEN today()-16 >= DtUltimaOriginacao THEN ' 16 a 30d sem originar'
		WHEN DtUltimaOriginacao >= today()-15  THEN ' Originaram nos últimos 15d'
		END AS DsTempoSemOriginacao
	,CASE 
		WHEN StBloqueioEmpresa = 'B' THEN 'Bloqueados'
		WHEN DtUltimaEfetivacao IS NULL THEN 'Nunca Efetivaram'
		WHEN intnx('month',today(),-5,'same') >= DtUltimaEfetivacao THEN '+ 5 Meses sem efetivar'
		WHEN intnx('month',today(),-3,'same') >= DtUltimaEfetivacao THEN '3 a 4 Meses sem efetivar' 
		WHEN intnx('month',today(),-1,'same') >= DtUltimaEfetivacao  THEN '1 a 2 meses sem efetivar'
		WHEN today()-16 >= DtUltimaEfetivacao THEN ' 16 a 30d sem efetivar'
		WHEN DtUltimaEfetivacao >= today()-15  THEN ' Efetivaram nos últimos 15d'
		END AS DsTempoSemEfetivacao
 FROM TbParceiroOriginacao ParceiroOriginacao

	LEFT JOIN basegrc.TbColaboradorFocal ColaboradorFocal
		ON  ParceiroOriginacao.CdFilialC = ColaboradorFocal.CdFilial
		AND ColaboradorFocal.NmGrupoProdutoMeta = 'Privado'
		AND ParceiroOriginacao.DsAtividadeFinanciamento = 'PRIVADO'

	LEFT JOIN bases.TBPARCEIROCOMERCIAL ParceiroComercial
		ON ParceiroOriginacao.CdParceiroComercial = ParceiroComercial.CdParceiroComercial
		
WHERE ParceiroOriginacao.TpAtividade = 8

;run;

proc export 
data=TbVisaoConveniosPrivado
file='/riscosbvf/BA/processos/tmp/TbVisaoConveniosPrivado.csv' replace
dbms=dlm;
delimiter=';';
run;

X 'mv /riscosbvf/BA/processos/tmp/TbVisaoConveniosPrivado.csv  /riscosbvf/BA/processos/output/';


/* =============================================================== */
/* ================ Producao e Mercado - Rodas ================== */
/* ============================================================== */

proc sql;
create table TbTempoData as 
select
	NuAnoMes
	,DtTempo
from bases.TbTempoData
where QtCorridosDiaMes = 1
	and DtTempo >= intnx('month',today(),-18)  ;run;


PROC SQL;
CREATE TABLE TbProducaoMercado AS
	SELECT
		PotencialRodas.NuAnoMes
		,TempoData.DtTempo
		,PotencialRodas.NmColaboradorC
		,PotencialRodas.DsLoginN1C
		,PotencialRodas.DsLoginN2C
		,PotencialRodas.DsLoginN3C
		,PotencialRodas.LstSubstituicaoC
		,PotencialRodas.CdFilialC
		,PotencialRodas.NmGrupoProduto
		,PotencialRodas.FxIdade
		,PotencialRodas.NmAreaEstruturaComercialC
		,PotencialRodas.NmSubEstruturaComercialC
		,PotencialRodas.NmCanalEstruturaComercialC
		,PotencialRodas.NmLoja
		,PotencialRodas.CdParceiroComercial
		,case
			when PotencialRodas.FlAtivo is null then 'NAO CADASTRADO'
			when PotencialRodas.FlAtivo = 'S' THEN 'ATIVO'
			when PotencialRodas.FlAtivo = 'N' THEN 'INATIVO'
			end as FlAtivo
		,PotencialRodas.NuCnpjLoja
		,PotencialRodas.TpCnae
		,PotencialRodas.NmLogradouro
		,PotencialRodas.NuEndereco
		,PotencialRodas.DsComplementoEndereco
		,PotencialRodas.NmBairro
		,PotencialRodas.CdCep
		,PotencialRodas.NmCidade
		,PotencialRodas.CdUf
		,PotencialRodas.PredominanciaProduto

		,SUM(PotencialRodas.VrProducao) AS VrProducao
		,SUM(PotencialRodas.QtContrato) AS QtContrato
		,SUM(PotencialRodas.VrGravamesMercado) AS VrGravamesMercado
		,SUM(PotencialRodas.QtGravamesMercado) AS QtGravamesMercado

	FROM tmp.TbPotencialRodas PotencialRodas
	
		LEFT JOIN TbTempoData TempoData 
			ON PotencialRodas.NuAnoMes = TempoData.NuAnoMes
	
	WHERE TempoData.DtTempo >= intnx('month',today(),-13)
		
	GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26
;RUN;


proc sql;
create table TbVisaoParceirosInativos as
select	
*
from TbProducaoMercado 
where FlAtivo <> 'ATIVO'
	and DtTempo >= intnx('month',today(),-6)
;run;



proc sql;
create table TipoLojas as
SELECT	DISTINCT
 NuCnpjLoja
,CASE 
        WHEN SUM(CASE WHEN FxIdade	<> 'ZeroKM' THEN QtGravamesMercado ELSE 0 END) > 
             SUM(CASE WHEN FxIdade	= 'ZeroKM' THEN QtGravamesMercado ELSE 0 END) 
        THEN 'Multimarcas' 
        ELSE 'Concessionária' 
    END AS TipoLoja
,CASE WHEN calculated TipoLoja = 'Multimarcas'  Then  SUM(CASE WHEN FxIdade	<> 'ZeroKM' THEN QtGravamesMercado ELSE 0 END) /
  													 (SUM(CASE WHEN FxIdade	= 'ZeroKM' THEN QtGravamesMercado ELSE 0 END)+
													  SUM(CASE WHEN FxIdade	<> 'ZeroKM' THEN QtGravamesMercado ELSE 0 END)) 

	 WHEN calculated TipoLoja = 'Concessionária'  Then  SUM(CASE WHEN FxIdade	= 'ZeroKM' THEN QtGravamesMercado ELSE 0 END) /
  													 (SUM(CASE WHEN FxIdade	= 'ZeroKM' THEN QtGravamesMercado ELSE 0 END)+
													  SUM(CASE WHEN FxIdade	<> 'ZeroKM' THEN QtGravamesMercado ELSE 0 END)) 
END As PercGravamesTipo FORMAT=numx18.2
from TbProducaoMercado
group by 1
;run;


proc sql;
create table TbShareFilial as
select	
	 NuAnoMes
	,CdFilialC
	,sum(QtContrato) as QtContrato
	,sum(VrGravamesMercado) AS VrGravamesMercado
	,sum(QtGravamesMercado) AS QtGravamesMercado

from TbProducaoMercado
where FlAtivo = 'ATIVO'
	and DtTempo >= intnx('month',today(),-6)
	and QtContrato > 0
group by 1,2
;run;


/*IMporta excel */
proc import datafile= "/riscosbvf/BA/processos/manuais/MotivoDescadastroPDV/MotivosDescadastro.xlsx"
out=MotivosDescadastro
dbms=xlsx replace;
sheet=Export
;run;

proc sort data=MotivosDescadastro ; 
by descending 'Data de Inativação'n 
;run;

proc sort data=MotivosDescadastro nodupkey; 
by 'Cód. Parceiro'n
;run;


proc sql;
create table TbVisaoCampanhaPDV as
select	distinct
	 Inativos.NuCnpjLoja
	,Sum(Case when Inativos.NuAnoMes IN (202502,202501,202412) 
			then Inativos.QtGravamesMercado else 0 end) /3 as Gravames3MCampanha
	,CASE WHEN Inativos.TpCnae = 'VEICULOS'  and calculated Gravames3MCampanha <= 3	   THEN 'Apto'
		  WHEN Inativos.TpCnae <> 'VEICULOS'  THEN 'Apto'
		  Else 'Inapto' end as ProspeccaoCN
from TbVisaoParceirosInativos Inativos
where 1=1
/*and Inativos.NuAnoMes IN (202502,202501,202412)*/
and Inativos.FxIdade <> 'ZeroKM'
and Inativos.NmGrupoProduto = 'Leves'
and  Inativos.NuCnpjLoja <> ''
/*and  Inativos.NuCnpjLoja  IN('01192333001528', '49708811000130')*/
group by 1
;run;


proc sql;
create table TbVisaoParceirosMercado as
select	
	 Inativos.NuAnoMes
	,Inativos.DtTempo
	,Inativos.NmColaboradorC
	,Inativos.DsLoginN1C
	,Inativos.DsLoginN2C
	,Inativos.DsLoginN3C
	,Inativos.LstSubstituicaoC
	,Inativos.CdFilialC
	,Inativos.NmGrupoProduto
	,Inativos.PredominanciaProduto
	,TipoLojas.TipoLoja
	,TipoLojas.PercGravamesTipo
	,'SEM PORTE' as Porte
	,Inativos.FxIdade
	,Inativos.NmAreaEstruturaComercialC
	,CASE
        WHEN Inativos.NmCidade = 'FORTALEZA' AND Inativos.CdUf = 'CE' THEN 'Canal Rodas e EGV I - Regional II'
        WHEN Inativos.NmCidade = 'SAO PAULO' AND Inativos.CdUf = 'SP' THEN 'Canal Rodas e EGV I - Regional I'
        WHEN Inativos.NmCidade = 'RIO DE JANEIRO' AND Inativos.CdUf = 'RJ' THEN 'Canal Rodas e EGV I - Regional II'
		ELSE Inativos.NmSubEstruturaComercialC END as NmSubEstruturaComercialC
	,Inativos.NmCanalEstruturaComercialC
	,Inativos.NmLoja
	,Inativos.CdParceiroComercial
	,Inativos.FlAtivo
	,Inativos.NuCnpjLoja
	,Inativos.TpCnae
	,Inativos.NmLogradouro
	,Inativos.NuEndereco
	,Inativos.DsComplementoEndereco
	,Inativos.NmBairro
	,Inativos.CdCep
	,Inativos.NmCidade
	,Inativos.CdUf
	,ParceiroComercial.FlSeguradora
	,Case When ParceiroComercial.FlAtivo = 'N' then put(datepart(ParceiroComercial.DtUltimaAtualizacao), date9.) End as DtInativação
	,MotivosDescadastro.Dslog as MotivoInatividade
	,Case 	when UPPER(MotivosDescadastro.Dslog) like '%FRAUDE%'							Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%INSPETORIA%'						Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%PLD%'								Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%CNPJ BAIXADO RECEITA FEDERAL%'		Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%CNPJ INAPTO RECEITA FEDERAL%'		Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%MOTIVO: SOLICITACAO DO COMERCIAL%'	Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%MOTIVO: DISTRATO COMERCIAL%'		Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%MOTIVO: RECLAMACAO%'				Then 'Inapto'
			when UPPER(MotivosDescadastro.Dslog) like '%MOTIVO: LOJA FECHOU%'				Then 'Inapto'
			else 'Apto' END AS AptoProspecção
	,Inativos.VrProducao
	,Inativos.QtContrato
	,Inativos.VrGravamesMercado
	,Inativos.QtGravamesMercado
	,Ativos.QtContrato as QtContratoFilial
	,Ativos.VrGravamesMercado as VrGravamesMercadoFilial
	,Ativos.QtGravamesMercado as QtGravamesMercadoFilial

	/*COLUNAS INSERIDAS PARA CAMPANHA COM FOCO EM CN*/
	,TbVisaoCampanhaPDV.Gravames3MCampanha FORMAT=numx18.2
	,Case When Calculated AptoProspecção = 'Inapto' Then 'Inapto'
		ELse COALESCE(TbVisaoCampanhaPDV.ProspeccaoCN,'Inapto') END AS ProspeccaoCN

	,Case when (Inativos.NmCidade IN ('SAO PAULO', 'ARUJA', 'BARUERI', 'BIRITIBA-MIRIM', 'CAIEIRAS', 'CAJAMAR', 'CARAPICUIBA', 
									  'COTIA', 'DIADEMA', 'EMBU', 'EMBU-GUACU', 'FERRAZ DE VASCONCELOS', 'FRANCISCO MORATO', 
									  'FRANCO DA ROCHA', 'GUARAREMA', 'GUARULHOS', 'ITAPECERICA DA SERRA', 'ITAPEVI', 'ITAQUAQUECETUBA', 
									  'JANDIRA', 'JUQUITIBA', 'MAIRIPORA', 'MAUA', 'MOGI DAS CRUZES', 'OSASCO', 'PIRAPORA DO BOM JESUS', 
									  'POA', 'RIBEIRAO PIRES', 'RIO GRANDE DA SERRA', 'SALESOPOLIS', 'SANTA ISABEL', 'SANTANA DE PARNAIBA', 
									  'SANTO ANDRE', 'SAO BERNARDO DO CAMPO', 'SAO CAETANO DO SUL', 'SAO LOURENÇO DA SERRA', 'SUZANO', 
									  'TABOAO DA SERRA', 'VARGEM GRANDE PAULISTA',
									  'SANTOS', 'SAO VICENTE', 'PRAIA GRANDE', 'GUARUJA','BERTIOGA', 'CUBATAO', 'MONGAGUA', 'ITANHAEM', 'PERUIBE') AND Inativos.CdUf = 'SP') 				THEN 'Canal de Negócios I'
		 when (Inativos.NmCidade NOT IN ('SAO PAULO', 'ARUJA', 'BARUERI', 'BIRITIBA-MIRIM', 'CAIEIRAS', 'CAJAMAR', 'CARAPICUIBA', 
									  'COTIA', 'DIADEMA', 'EMBU', 'EMBU-GUACU', 'FERRAZ DE VASCONCELOS', 'FRANCISCO MORATO', 
									  'FRANCO DA ROCHA', 'GUARAREMA', 'GUARULHOS', 'ITAPECERICA DA SERRA', 'ITAPEVI', 'ITAQUAQUECETUBA', 
									  'JANDIRA', 'JUQUITIBA', 'MAIRIPORA', 'MAUA', 'MOGI DAS CRUZES', 'OSASCO', 'PIRAPORA DO BOM JESUS', 
									  'POA', 'RIBEIRAO PIRES', 'RIO GRANDE DA SERRA', 'SALESOPOLIS', 'SANTA ISABEL', 'SANTANA DE PARNAIBA', 
									  'SANTO ANDRE', 'SAO BERNARDO DO CAMPO', 'SAO CAETANO DO SUL', 'SAO LOURENÇO DA SERRA', 'SUZANO', 
									  'TABOAO DA SERRA', 'VARGEM GRANDE PAULISTA',
									  'SANTOS', 'SAO VICENTE', 'PRAIA GRANDE', 'GUARUJA','BERTIOGA', 'CUBATAO', 'MONGAGUA', 'ITANHAEM', 'PERUIBE') AND Inativos.CdUf = 'SP')				THEN 'Canal de Negócios II'
		  when Inativos.CdUf in ('MG','RJ','ES') 										THEN 'Canal de Negócios III'
		  when Inativos.CdUf in ('AC','AP','AM','PA','RO','RR','TO',
								'AL','BA','CE','MA','PB','PE','PI','RN','SE')			THEN 'Canal de Negócios IV'
		  when Inativos.CdUf in ('MT','MS','GO','DF','PR') 								THEN 'Canal de Negócios V'
		  when Inativos.CdUf in ('RS','SC') 											THEN 'Canal de Negócios VI'
		  ELSE 'Sem Classificação'
		END AS FilialCN

from TbVisaoParceirosInativos Inativos

	left join TbShareFilial Ativos
		on Inativos.CdFilialC = Ativos.CdFilialC
	   and Inativos.NuAnoMes = Ativos.NuAnoMes

	Left join TipoLojas as TipoLojas
		on Inativos.NuCnpjLoja = TipoLojas.NuCnpjLoja

	Left Join MotivosDescadastro as MotivosDescadastro
		on MotivosDescadastro.'Cód. Parceiro'n = Inativos.CdParceiroComercial

	Left join tmp.tbparceirocomercial as ParceiroComercial
		on ParceiroComercial.CdParceiroComercial = Inativos.CdParceiroComercial

	LEFT JOIN TbVisaoCampanhaPDV as TbVisaoCampanhaPDV
		on TbVisaoCampanhaPDV.NuCnpjLoja = Inativos.NuCnpjLoja
;run;



 /*SUBSTITUI TUDO QUE FOI "MISSING OU '.' POR '0'*/


data work.TbVisaoParceirosMercado;
	set work.TbVisaoParceirosMercado;
 
	array num_array _numeric_;
	do over num_array;
		if missing(num_array) then num_array = 0;
	end;
run;

proc export 
data=TbVisaoParceirosMercado
file='/riscosbvf/BA/processos/output/TbVisaoParceirosMercado.csv' replace
dbms=dlm;
delimiter=';';
run;

X "mv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoParceirosMercado.csv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/processados/ ";


proc sql;
create table TbVerificaUltimaProducao as 
select

	 NuCnpjLoja
	,CdParceiroComercial
	,NmColaboradorC
	,DsLoginN1C
	,DsLoginN2C
	,DsLoginN3C
	,LstSubstituicaoC
	,NmAreaEstruturaComercialC
	,NmSubEstruturaComercialC
	,NmCanalEstruturaComercialC
	,NmLoja
	,NuCnpjLoja
	,TpCnae
	,NmLogradouro
	,NuEndereco
	,DsComplementoEndereco
	,NmBairro
	,CdCep
	,NmCidade
	,CdUf
	,max(DtTempo) as DtUltimaProducaoMercado format date9.
	,sum(VrProducao) AS VrProducao
	,sum(QtContrato) AS QtContrato
	,sum(VrGravamesMercado) AS VrGravamesMercado
	,sum(QtGravamesMercado) AS QtGravamesMercado

from TbProducaoMercado
where FlAtivo = 'ATIVO'
and DtTempo = intnx('month',today()-1,-0)
group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20
having sum(VrGravamesMercado,VrProducao) > 0

;run;


proc sql;
create table TbVerificaUltimaBV as 
select
	VerificaUltimaProducao.NuCnpjLoja
	,VerificaUltimaProducao.CdParceiroComercial

	,VerificaUltimaProducao.NmColaboradorC
	,VerificaUltimaProducao.DsLoginN1C
	,VerificaUltimaProducao.DsLoginN2C
	,VerificaUltimaProducao.DsLoginN3C
	,VerificaUltimaProducao.LstSubstituicaoC
	,VerificaUltimaProducao.NmAreaEstruturaComercialC
	,VerificaUltimaProducao.NmSubEstruturaComercialC
	,VerificaUltimaProducao.NmCanalEstruturaComercialC
	,VerificaUltimaProducao.NmLoja
	,VerificaUltimaProducao.NuCnpjLoja
	,VerificaUltimaProducao.TpCnae
	,VerificaUltimaProducao.NmLogradouro
	,VerificaUltimaProducao.NuEndereco
	,VerificaUltimaProducao.DsComplementoEndereco
	,VerificaUltimaProducao.NmBairro
	,VerificaUltimaProducao.CdCep
	,VerificaUltimaProducao.NmCidade
	,VerificaUltimaProducao.CdUf
	,max(datepart(ExtContrato.DtContrato)) as DtUltimaProducaoBV format date9.
	,sum(VerificaUltimaProducao.VrProducao) AS VrProducao
	,sum(VerificaUltimaProducao.QtContrato) AS QtContrato
	,sum(VerificaUltimaProducao.VrGravamesMercado) AS VrGravamesMercado
	,sum(VerificaUltimaProducao.QtGravamesMercado) AS QtGravamesMercado
from TbVerificaUltimaProducao VerificaUltimaProducao

	left join bases.TbExtContrato ExtContrato 
		on VerificaUltimaProducao.CdParceiroComercial =  ExtContrato.CdParceiroComercial

		left join basegrc.TbGrupoProdutoMeta GrupoProdutoMeta
			on  ExtContrato.CdGrupoSubProduto = GrupoProdutoMeta.CdGrupoSubProduto

		 
where GrupoProdutoMeta.NmGrupoProdutoMeta in ('Leves','Motos','Pesados','CVG Leves','CVG Pesados')

group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20
;run;


data TbProducaoFinal;
set TbVerificaUltimaProducao TbVerificaUltimaBV;run;


proc sql;
create table TbProducaoFinal as 
select
	NuCnpjLoja
	,CdParceiroComercial
	,NmColaboradorC
	,DsLoginN1C
	,DsLoginN2C
	,DsLoginN3C
	,LstSubstituicaoC
	,NmAreaEstruturaComercialC
	,NmSubEstruturaComercialC
	,NmCanalEstruturaComercialC
	,NmLoja
	,NuCnpjLoja
	,TpCnae
	,NmLogradouro
	,NuEndereco
	,DsComplementoEndereco
	,NmBairro
	,CdCep
	,NmCidade
	,CdUf
	,max(intnx('month',DtUltimaProducaoBV,0)) as DtUltimaProducaoBV format date9.
	,sum(VrProducao) AS VrProducao
	,sum(QtContrato) AS QtContrato
	,sum(VrGravamesMercado) AS VrGravamesMercado
	,sum(QtGravamesMercado) AS QtGravamesMercado
from TbProducaoFinal
group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20
;run;


proc sql;
create table TbVisaoParceirosAtivos as 
  select
	ProducaoFinal.NuCnpjLoja
	,ProducaoFinal.CdParceiroComercial
	,ProducaoFinal.NmColaboradorC
	,ProducaoFinal.DsLoginN1C
	,ProducaoFinal.DsLoginN2C
	,ProducaoFinal.DsLoginN3C
	,ProducaoFinal.LstSubstituicaoC
	,ProducaoFinal.NmAreaEstruturaComercialC
	,ProducaoFinal.NmSubEstruturaComercialC
	,ProducaoFinal.NmCanalEstruturaComercialC
	,ProducaoFinal.NmLoja AS NmParceiroComercial
	,ProducaoFinal.NuCnpjLoja
	,ProducaoFinal.TpCnae
	,ProducaoFinal.NmLogradouro
	,ProducaoFinal.NuEndereco
	,ProducaoFinal.DsComplementoEndereco
	,ProducaoFinal.NmBairro
	,ProducaoFinal.CdCep
	,ProducaoFinal.NmCidade
	,ProducaoFinal.CdUf
	,ProducaoFinal.DtUltimaProducaoBV
	,ParceiroComercial.FlSeguradora
	
	,case 
		when ProducaoFinal.DtUltimaProducaoBV is null  then 'Nunca Produziu no BV'
		when intnx('month',today(),-12) >= ProducaoFinal.DtUltimaProducaoBV then '+ 12 Meses sem produzir no BV'
		when intnx('month',today(),-8) >= ProducaoFinal.DtUltimaProducaoBV then '8 a 12 Meses sem Produzir no BV'
		when intnx('month',today(),-4) >= ProducaoFinal.DtUltimaProducaoBV then '4 a 6 Meses sem Produzir no BV'
		when intnx('month',today(),-1) >= ProducaoFinal.DtUltimaProducaoBV then '1 a 3 Meses sem Produzir no BV'
		when year(ProducaoFinal.DtUltimaProducaoBV)*100+month(today()) = year(today())*100+month(today()) then 'Produziu no mes atual no BV'
		end as DsTempoSemProducaoBV
	,ProducaoFinal.VrProducao
	,ProducaoFinal.QtContrato
	,ProducaoFinal.VrGravamesMercado
	,ProducaoFinal.QtGravamesMercado
  from TbProducaoFinal ProducaoFinal 
  left join tmp.TbParceiroComercial ParceiroComercial 
  	on ProducaoFinal.CdParceiroComercial = ParceiroComercial.CdParceiroComercial
  group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27
  ;run;

proc export 
data=TbVisaoParceirosAtivos
file='/projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoParceirosAtivos.csv' replace
dbms=dlm;
delimiter=';';
run;

X "mv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbVisaoParceirosAtivos.csv  /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/processados/ ";

%include '/infogrc/campanha_ativabv/Script/CampanhaPDV.sas';

GOPTIONS NOACCESSIBLE;
%LET _CLIENTTASKLABEL=;
%LET _CLIENTPROCESSFLOWNAME=;
%LET _CLIENTPROJECTPATH=;
%LET _CLIENTPROJECTPATHHOST=;
%LET _CLIENTPROJECTNAME=;
%LET _SASPROGRAMFILE=;
%LET _SASPROGRAMFILEHOST=;
quit;run;
ODS _ALL_ CLOSE;
