/* ========================================================================================== */
/* Data : 22/11/2023 																		  */
/* Resp.: Gustavo Domingues - MIS IGE						       					 		  */
/* Descrição.: Alterado tabela da lib ConvSimu para tbsimulação 							  */    		
/* ========================================================================================== */
/* Data : 22/05/2025 																		  */
/* Resp.: Marcio Shiroma						       					 		  			  */
/* Descrição.: Inclui a campo de CNPJFAVORECIDO e dados do Seguro Placa Solar				  */    		
/* ========================================================================================== */

option compress = binary;
%include '/infogrc/utils/all-includes.sas';   
%include '/projetos/MISV/sas-misv-base-lib/scripts/ConectaDB.sas';
%include '/projetos/MISV/sas-misv-base-lib/scripts/libname.sas';
libname GCP '/projetos/MISV/data/bases/gcp';


PROC SQL;
CONNECT TO bigquery AS perm (project='bv-saem-dtm' credfile='/projetos/acessos/bq/em/saem-dtm.json'
      schema='bv-pdbd-prd' READ_MODE=storage);
   CREATE TABLE TbPropEfetivacaoLeves AS
   SELECT *	FROM connection to perm
     	(
			SELECT 
				*
			FROM bv-pdbd-prd.dvry_anly_cienciadado.tb_apnp_bv_v2_kraken ORDER BY TsInclusao DESC
		);

   DISCONNECT FROM perm
;QUIT;
 

data TbPropEfetivacaoLevesFinal;

LENGTH		safra	$10.;
informat	safra	$10.;
format		safra	$10.;

LENGTH		dtreferencia	$10.;
informat	dtreferencia	$10.;
format		dtreferencia	$10.;

set TbPropEfetivacaoLeves;
run;

PROC SORT DATA=TbPropEfetivacaoLevesFinal NODUPKEY;BY NuProposta;RUN;


PROC SQL;
CREATE TABLE GCP.TbPropEfetivacaoLeves AS 
SELECT 
	 safra	
	,dtreferencia	
	,nuproposta	
	,idchavemodelo	
	,grupocontrole	
	,prob1	
	,gh	
	,Tsinclusao

FROM TbPropEfetivacaoLevesFinal
WHERE grupocontrole = 0
AND gh IN (3,4,5)
;run;


%CRIAVARDB;
proc sql; 
%CONECTADB(server=PTA);
	CREATE TABLE TbPropostaSeguro AS 
	SELECT * FROM connection to dbcon
	( 

			SELECT
				 PropostaSeguro.NuProposta
				,ProdutoSeguro.CdTipoSeguro
				,ProdutoSeguro.CdProdutoSeguro
				,ProdutoSeguro.NmProdutoSeguro
				,PropostaSeguro.VrSeguro
				
			FROM DBCRED.TbPropostaSeguro PropostaSeguro
			
				INNER JOIN DBA.TbProposta Proposta
					ON  PropostaSeguro.NuProposta = Proposta.NuProposta
					AND Proposta.StProposta IN ('A','PA')
					
				LEFT JOIN DBCONTRATOSEGURO.TbProdutoSeguro ProdutoSeguro
					ON  PropostaSeguro.CdProdutoSeguro = ProdutoSeguro.CdProdutoSeguro					
					
		)
;QUIT; 


proc sql;
create table TbExtPropostaSeguros as
select
	 PropostaSeguro.NuProposta
	,count(*) as QtSeguros

	,max(case when PropostaSeguro.CdTipoSeguro = 4 then 1 else 0 end) as FlDFI
	,max(case when PropostaSeguro.CdTipoSeguro = 2 then 1 else 0 end) as FlBVMais
	,max(case when PropostaSeguro.CdTipoSeguro in (3,5) then 1 else 0 end) as FlCap
	,max(case when PropostaSeguro.CdTipoSeguro = 6 then 1 else 0 end) as FlPlacaSolar

	,sum(case when PropostaSeguro.CdTipoSeguro = 1 then 1 else 0 end) as QtDemais
	,max(case when PropostaSeguro.CdTipoSeguro = 1 then 1 else 0 end) as FlDemais
	,sum(case when PropostaSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro <> 11 then 1 else 0 end) as QtDemaisSemCompleto
	,max(case when PropostaSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro <> 11 then 1 else 0 end) as FlDemaisSemCompleto

	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 33 then 1 else 0 end) as FlCap03 
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 35 then 1 else 0 end) as FlCap05
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 37 then 1 else 0 end) as FlCap07
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 30 then 1 else 0 end) as FlCap10
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 38 then 1 else 0 end) as FlCap12
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 39 then 1 else 0 end) as FlCap15
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 31 then 1 else 0 end) as FlCap19

	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 42 then 1 else 0 end) as FlCap25
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 43 then 1 else 0 end) as FlCap35
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 44 then 1 else 0 end) as FlCap40
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 45 then 1 else 0 end) as FlCap50
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 46 then 1 else 0 end) as FlCap96
	,max(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 47 then 1 else 0 end) as FlCap145

	,max(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 595 then 1 else 0 end) as FlPlacaSolar12
	,max(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 596 then 1 else 0 end) as FlPlacaSolar24
	,max(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 597 then 1 else 0 end) as FlPlacaSolar36

	,max(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 11 then 1 else 0 end) as FlCompleto
	,max(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 12 then 1 else 0 end) as FlGarantiaMecanica
	,max(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 13 then 1 else 0 end) as FlRCF
	,max(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 14 then 1 else 0 end) as FlCasco
	,max(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 15 then 1 else 0 end) as FlGap

	,sum(PropostaSeguro.VrSeguro) as VrSeguros

	,sum(case when PropostaSeguro.CdTipoSeguro = 4 then PropostaSeguro.VrSeguro else 0 end) as VrDFI
	,sum(case when PropostaSeguro.CdTipoSeguro = 2 then PropostaSeguro.VrSeguro else 0 end) as VrBVMais
	,sum(case when PropostaSeguro.CdTipoSeguro in (3,5) then PropostaSeguro.VrSeguro else 0 end) as VrCap
	,sum(case when PropostaSeguro.CdTipoSeguro = 6 then PropostaSeguro.VrSeguro else 0 end) as VrPlacaSolar

	,sum(case when PropostaSeguro.CdTipoSeguro = 1 then PropostaSeguro.VrSeguro else 0 end) as VrDemais
	,max(case when PropostaSeguro.CdTipoSeguro = 1 then PropostaSeguro.VrSeguro else 0 end) as VrDemaisMax
	,max(case when PropostaSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro <> 11 then PropostaSeguro.VrSeguro else 0 end) as VrDemaisSemCompletoMax

	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 33 then PropostaSeguro.VrSeguro else 0 end) as VrCap03
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 35 then PropostaSeguro.VrSeguro else 0 end) as VrCap05
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 37 then PropostaSeguro.VrSeguro else 0 end) as VrCap07
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 30 then PropostaSeguro.VrSeguro else 0 end) as VrCap10
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 38 then PropostaSeguro.VrSeguro else 0 end) as VrCap12
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 39 then PropostaSeguro.VrSeguro else 0 end) as VrCap15
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 31 then PropostaSeguro.VrSeguro else 0 end) as VrCap19

	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 42 then PropostaSeguro.VrSeguro else 0 end) as VrCap25
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 43 then PropostaSeguro.VrSeguro else 0 end) as VrCap35
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 44 then PropostaSeguro.VrSeguro else 0 end) as VrCap40
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 45 then PropostaSeguro.VrSeguro else 0 end) as VrCap50
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 46 then PropostaSeguro.VrSeguro else 0 end) as VrCap96
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro in (3,5) and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 47 then PropostaSeguro.VrSeguro else 0 end) as VrCap145

	,sum(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 595 then PropostaSeguro.VrSeguro else 0 end) as VrPlacaSolar12
	,sum(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 596 then PropostaSeguro.VrSeguro else 0 end) as VrPlacaSolar24
	,sum(case when PropostaSeguro.CdTipoSeguro = 6 and PropostaSeguro.CdProdutoSeguro = 597 then PropostaSeguro.VrSeguro else 0 end) as VrPlacaSolar36

	,sum(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 11 then PropostaSeguro.VrSeguro else 0 end) as VrCompleto
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 12 then PropostaSeguro.VrSeguro else 0 end) as VrGarantiaMecanica
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 13 then PropostaSeguro.VrSeguro else 0 end) as VrRCF
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 14 then PropostaSeguro.VrSeguro else 0 end) as VrCasco
	,sum(case when GrupoProdutoSeguro.CdTipoSeguro = 1 and GrupoProdutoSeguro.CdGrupoProdutoSeguro = 15 then PropostaSeguro.VrSeguro else 0 end) as VrGap

from TbPropostaSeguro PropostaSeguro

	left join automati.TBSEG_PRODUTOSEGURO GrupoProdutoSeguro
/*			  basegrc.TbGrupoProdutoSeguro GrupoProdutoSeguro*/
		on  PropostaSeguro.CdProdutoSeguro = GrupoProdutoSeguro.CdProdutoSeguro

group by 
	 PropostaSeguro.NuProposta
;run;


%CRIAVARDB;
proc sql;
%CONECTADB(server = BI);
create table TbRankingCetip as 
select * from connection to dbcon
(
WITH
	 TbDataUltimoArquivo AS (
		SELECT MAX(substr(NmArquivo,13,8)) AS DtUltimoArquivo
		FROM DWBI_DTWH.TbRanking 
		where NmArquivo not like '%PRK%'
	
	 )

	,TbCetipRankingMesAtual AS (
		SELECT 
			year(CAST(substr(Ranking.NmArquivo,13,8) AS DATE))*100+month(CAST(substr(Ranking.NmArquivo,13,8) AS DATE)) AS NuAnoMes
			,Ranking.NuCnpjLoja
			,Ranking.QtBancos
			,Ranking.NuRankingCliente

		FROM DWBI_DTWH.TbRanking Ranking
			INNER JOIN TbDataUltimoArquivo DataUltimoArquivo
				ON substr(Ranking.NmArquivo,13,8) = DataUltimoArquivo.DtUltimoArquivo
				AND substr(DataUltimoArquivo.DtUltimoArquivo,7,2) <> '01'
		WHERE  Ranking.CdTipoRegistro = 'D'
		AND  Ranking.NmArquivo not like '%PRK%'
			
	)

	,TbCetipRankingMesFechado AS (
		SELECT
			year(CAST(substr(Ranking.NmArquivo,13,8) AS DATE)-1)*100+month(CAST(substr(Ranking.NmArquivo,13,8) AS DATE)-1) AS NuAnoMes
			,Ranking.NuCnpjLoja
			,Ranking.QtBancos
			,Ranking.NuRankingCliente

		FROM DWBI_DTWH.TbRanking Ranking
		WHERE substr(Ranking.NmArquivo,19,2) = '01'
		  AND Ranking.CdTipoRegistro = 'D'
		  AND  Ranking.NmArquivo not like '%PRK%'
			 
	)

	,TbCetipRankingFinal AS (
		SELECT * FROM TbCetipRankingMesAtual UNION ALL
		SELECT * FROM TbCetipRankingMesFechado 
	)

	SELECT * FROM TbCetipRankingFinal
/*		WHERE NuAnoMes >= 201901*/
	)
;run;



/*data bases.TbPropEfetivacaoLeves;
set dscience.TbEfetivacaoLeves
;run;*/

/**/
/**/
/*proc sql;*/
/*create table TbPropEfetivacaoLeves as*/
/*select */
/*	l.* */
/*	,o.NmGrupoProdutoMeta */
/*	,o.StProposta */
/*	,o.FlPropostaAPNP */
/*	,DtStatusProposta*/
/*from dscience.TbPropEfetivacaoLeves l*/
/*	left join bases.TbOriginacao o */
/*	on	l.NuProposta = o.NuProposta*/
/*;run;*/
/**/
/**/
/*proc sql;*/
/*create table aaa as*/
/*select **/
/*from basegrc.TbGrupoProdutoMeta*/
/*;run;*/
/**/
/**/
/*proc sql;*/
/*create table a as */
/*select distinct StProposta*/
/*from  TbPropEfetivacaoLeves*/
/*where StProposta = 'A'*/
/*;run;*/

data MsgProposta_V1 (keep=NuAnoMes NuProposta UltMensageria ProbabilidadeAprovacao) ;
    set CONVSIMU.tbsimulacoes (where=(NuAnoMes >= &safraA1.))
;run;

data MsgProposta ;
    set MsgProposta_V1 (where=(NuProposta <> .))
;run;


PROC SORT DATA=MsgProposta NODUPKEY;
BY NuProposta;
RUN;

PROC SQL; CREATE INDEX NuProposta ON MsgProposta; QUIT;

/*Inclui o NuCnpjLojaFavorecido para o Solar - 22-05-25 - Shiroma*/
PROC SQL;
CREATE TABLE TbPropostaAPNP AS 
SELECT
	 Originacao.DtEntradaProposta
	,Originacao.DtAtualizacao
	,case
		when Originacao.QtDiasUteisMaturacao > 10 then 'Acima de 10 Dias'
		when Originacao.QtDiasUteisMaturacao >  5 then '6 a 10 Dias'
		when Originacao.QtDiasUteisMaturacao > -1 then '0 a 5 Dias'
	 end as FxDiasUteisMaturacao
	,originacao.QtDiasUteisMaturacao
	,originacao.NuProposta
	,case when PropEfetivacaoLeves.NuProposta is not null then 1 else 0 end as FlIncentivo

	,originacao.CdParceiroComercial
	,originacao.NmParceiroComercial
	,originacao.NuCnpjLojaFavorecido
	,originacao.NmParceiroComercialFavorecido
	,originacao.NmParceiroComercialCoban
	,originacao.NmPromotora
	,originacao.NmGrupoProdutoMeta
	,originacao.DsTipoCanalProducao
	,originacao.NmPessoa
	,originacao.NuCpfCnpj
	,originacao.TpPessoa
	/*,Contato.NuDdd1||Contato.NuTelefone1 as NuTelefone1*/
	,NuTelefone1
	/*,Contato.NuDDD2||Contato.NuTelefone2 as NuTelefone2*/
	,NuTelefone2
	/*,Contato.NuDDD3||Contato.NuTelefone3 as NuTelefone3*/
	,NuTelefone3
	/*,Contato.Email1*/
	,Contato.DsEmail as Email1
	/*,Contato.Email2*/
	,Contato.DsEmail2 as Email2
	,originacao.NmColaborador
	,originacao.NmCanalEstruturaComercial
	,originacao.NmAreaEstruturaComercial
	,originacao.NmSubEstruturaComercialA
	,originacao.DsLoginN1
	,originacao.DsloginN2A
	,originacao.DsloginN3A
	,originacao.LstSubstituicao
	,ColaboradorFocal.LstColaboradorFocal
	,originacao.FxIdade
	,originacao.CdModelo
	,originacao.CdMarca
	,originacao.AaFabricacao
	,originacao.pgto_loja as TpMercado
	,case 
		when originacao.pgto_loja = 'N' then 'Prop paga na concorrência, em outra loja'
		when originacao.pgto_loja = 'S' then 'Prop paga na concorrência, na mesma loja'
		else 'Proposta em aberto' end as DsTpMercado
	,originacao.FlCCB
	,originacao.StAverbacao
	,originacao.QtParcelas
	,CetipRanking.QtBancos	
	,CetipRanking.NuRankingCliente AS RankingCliente
	,originacao.NuScoreFim
	,originacao.FxScoreFim
	,originacao.FlTxAlterada
	,originacao.FxEntrada
	,originacao.VrLiberado
	,originacao.VrPrestacao
	,MsgProposta.ProbabilidadeAprovacao as NuRating

	,ExtPropostaSeguros.FlCompleto	
	,ExtPropostaSeguros.VrCompleto
	,ExtPropostaSeguros.FlBVMais		
	,ExtPropostaSeguros.VrBVMais
	,ExtPropostaSeguros.QtDemaisSemCompleto	
	,ExtPropostaSeguros.VrDemaisSemCompletoMax
	,ExtPropostaSeguros.FlCap	
	,ExtPropostaSeguros.VrCap
	,ExtPropostaSeguros.FlPlacaSolar
	,ExtPropostaSeguros.VrPlacaSolar Format COMMAX10.2

	,MsgProposta.UltMensageria

	,originacao.CdColaboradorC
	,originacao.NmColaboradorC
	,originacao.DsLoginN1C
	,originacao.CdFilialC
	,originacao.NmFilialC
	,originacao.CdAreaEstruturaComercialC
	,originacao.NmAreaEstruturaComercialC
	,originacao.DsLoginN2C
	,originacao.DsLoginN3C
	,originacao.NmSubEstruturaComercialC
	,originacao.LstSubstituicaoC
	,tbfiltrocvg.FiltroCVG
	,originacao.DsLoginOriginador

FROM Tmp.TbOriginacao Originacao

	left join TbRankingCetip CetipRanking
		on  Originacao.NuAnoMes	     = CetipRanking.NuAnoMes
		and Originacao.NuCnpjLoja 	 = put(CetipRanking.NuCnpjLoja,z14.)

	/*left join FI_PRODT.TBDBMKUNIFICADA Contato
		on Originacao.NuCpfCnpj = Contato.NuCpfCnpj*/
	left join bases.TbPessoa Contato
		on Originacao.NuCpfCnpj = Contato.NuCpfCnpj

	left join basegrc.TbColaboradorFocal ColaboradorFocal
		on  Originacao.CdFilial = ColaboradorFocal.CdFilial
		and Originacao.NmGrupoProdutoMeta = ColaboradorFocal.NmGrupoProdutoMeta

	left join TbExtPropostaSeguros ExtPropostaSeguros
		on  Originacao.NuProposta = ExtPropostaSeguros.NuProposta

	left join GCP.TbPropEfetivacaoLeves PropEfetivacaoLeves
		on  Originacao.NuProposta = PropEfetivacaoLeves.NuProposta
/*		and PropEfetivacaoLeves.Grupo = 'teste'*/
/*		and PropEfetivacaoLeves.FlIncentivo = 'Sim'*/

	left join MsgProposta MsgProposta
	 on MsgProposta.nuproposta = Originacao.nuproposta

	 	left join basegrc.tbfiltrocvg tbfiltrocvg
	 on Originacao.nuproposta = tbfiltrocvg.nuproposta

WHERE Originacao.FlPropostaAPNP = 1
;run;



PROC SQL;
CREATE TABLE TbProducaoAPNP AS 
SELECT
	 Producao.NmGrupoProdutoMeta
	,Producao.NmColaborador
	,Producao.NmCanalEstruturaComercial
	,Producao.NmAreaEstruturaComercial
	,Producao.NmSubEstruturaComercialA
	,Producao.DsLoginN1
	,Producao.DsloginN2A
	,Producao.DsloginN3A
	,Producao.LstSubstituicao
	,ColaboradorFocal.LstColaboradorFocal
	,Producao.QtCorridosDiaUtilMes
	,Producao.QtTotalDiaUtilMes

	,Producao.CdColaboradorC
	,Producao.NmColaboradorC
	,Producao.DsLoginN1C
	,Producao.CdFilialC
	,Producao.NmFilialC
	,Producao.CdAreaEstruturaComercialC
	,Producao.NmAreaEstruturaComercialC
	,Producao.DsLoginN2C
	,Producao.DsLoginN3C
	,Producao.NmSubEstruturaComercialC
	,Producao.LstSubstituicaoC
	,tbfiltrocvg.FiltroCVG
	,Producao.DsLoginOriginador

	,Sum(Producao.VrProducao) as VrProducao
	,Sum(Producao.VrProducaoDiaUtil) as VrProducaoDiaUtil
	,Sum(Producao.VrProducaoProjetado) as VrProducaoProjetado
	,Sum(Producao.FlCompleto) as FlCompleto
	,Sum(Producao.VrCompleto) as VrCompleto
	,Sum(Producao.FlBVMais) as FlBVMais
	,Sum(Producao.VrBVMais) as VrBVMais
	,Sum(Producao.FlDemaisSemCompleto) as FlDemaisSemCompleto
	,Sum(Producao.VrDemaisSemCompletoMax) as VrDemaisSemCompleto
	,Sum(Producao.FlPlacaSolar) as FlPlacaSolar
	,Sum(Producao.VrPlacaSolar) as VrPlacaSolar Format COMMAX10.2
FROM Tmp.TbProducao Producao

	left join basegrc.TbColaboradorFocal ColaboradorFocal
		  on Producao.CdFilialC = ColaboradorFocal.CdFilial
		 and Producao.NmGrupoProdutoMeta = ColaboradorFocal.NmGrupoProdutoMeta

	left join basegrc.tbfiltrocvg tbfiltrocvg
	 on Producao.nuproposta = tbfiltrocvg.nuproposta
		 
Where NuAnoMes = year(today())*100+month(today())
Group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25
;run;


/*META DOS GRS*/
PROC SQL;
CREATE TABLE TbMetasAPNP as 
SELECT 
	 METACOLABORADOR.NuAnoMes
	,METACOLABORADOR.NmGrupoProdutoMeta
	,ESTRUTURACOMERCIAL.NmColaborador
	,ESTRUTURACOMERCIAL.NmCanalEstruturaComercial
	,ESTRUTURACOMERCIAL.NmAreaEstruturaComercial
	,ESTRUTURACOMERCIAL.NmSubEstruturaComercialA
	,METACOLABORADOR.DsLoginN1
	,ESTRUTURACOMERCIAL.DsloginN2A
	,ESTRUTURACOMERCIAL.DsloginN3A
	,ESTRUTURACOMERCIAL.LstSubstituicao
	,ColaboradorFocal.LstColaboradorFocal
	,sum(Coalesce(METACOLABORADOR.VrMetaN1,0)) as MetaGR
	,sum(Coalesce(METACOLABORADOR.VrMetaN2,0)) as MetaGF

From BASES.TBMETACOLABORADOR METACOLABORADOR
	Left Join BASES.TBESTRUTURACOMERCIAL ESTRUTURACOMERCIAL
		 ON METACOLABORADOR.CdFilial = ESTRUTURACOMERCIAL.CdFilial 
		 and METACOLABORADOR.NuAnoMes = ESTRUTURACOMERCIAL.NuAnoMes 
		 and METACOLABORADOR.DsLoginN1 = ESTRUTURACOMERCIAL.DsLoginN1

	left join basegrc.TbColaboradorFocal ColaboradorFocal
		 on METACOLABORADOR.CdFilial = ColaboradorFocal.CdFilial
		 and METACOLABORADOR.NmGrupoProdutoMeta = ColaboradorFocal.NmGrupoProdutoMeta

Where METACOLABORADOR.TpValor = "VrProducao" 
	and METACOLABORADOR.NuAnoMes = year(today())*100+month(today())
Group by 1,2,3,4,5,6,7,8,9,10,11;
Quit;


Data Bases.TbRelatorioAPNP;
Set TbPropostaAPNP
	TbProducaoAPNP
	TbMetasAPNP;
Run;

proc export 
data=Bases.TbRelatorioAPNP
file='/projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbRelatorioAPNP.csv' replace
dbms=dlm;
delimiter=';';
run;

X 'mv /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/TbRelatorioAPNP.csv /projetos/MISV/sas-misv-base-indicadores-varejo/outbound/processados/';


/*proc export */
/*data=TbRelatorioAPNP*/
/*file='/riscosbvf/BA/processos/tmp/TbRelatorioAPNP.csv' replace*/
/*dbms=dlm;*/
/*delimiter=';';*/
/*run;*/
/**/
/*X "mv  /riscosbvf/BA/processos/tmp/TbRelatorioAPNP.csv  /riscosbvf/BA/processos/output/ ";*/
