# Diff dos EGPs QUASE-IGUAIS (deduplicado)
Comparacao interna de cada par. Credenciais redigidas como `<REDACTED>`.
Tarefas identificadas pelo CodeTask-id (cada tarefa aparece uma vez).


## 1004-Relatório_Encerramento_PU.egp  -  Jurídico vs Riscos

**Tarefas so em Riscos:** CodeTask-KzU3EiQPkkskifpA, CodeTask-Os8Sx2cvC3kBAo3J, CodeTask-iGQfUHRRLF7Xp24p, CodeTask-uaWoeSCEkqskFjP8


## 1500 - Financeiro Sintetico.egp  -  Jurídico vs Riscos

**Tarefas so em Riscos:** CodeTask-3hiMIwTjT6NKMH6M, CodeTask-4XXRsiICtCqfIiCX, CodeTask-7JEBmUOcd5DKVzxX, CodeTask-8iL96sENO38ZN5rj, CodeTask-Ddi2ldcI1eIhvJoE, CodeTask-DeST5DxHpcuckG2c, CodeTask-Ej9lZRJtr21CmfLh, CodeTask-NG3WzJy6CudeZtjC, CodeTask-WUaZZUu2bq2LiWa9, CodeTask-i1pt3BgKh4uPLHJ3, CodeTask-jWeFn19MbvEU2WfV, CodeTask-zKYhQEdMs84TZBiC


## BaseUnica.egp  -  Negócios e Produtos Relacional e Seguros vs Seguros


### CodeTask-SfmUSIsOhjLWDwJs  (+3/-0)
```diff
@@ -106,2 +106,5 @@
 	 and prodseg.cdseguradora IN (472399  /*BBSEG*/)
+	) or
+	(evenseg.DtEventoSeguro>='2026-02-12'
+	 and prodseg.cdseguradora IN (109719  /*CARDIF*/)
 	)
```


### CodeTask-kFFvqX9pyBsBSwQ5  (+7/-0)
```diff
@@ -109,2 +109,9 @@
 					AND extract(month from dtprocessamento) >=7
+			UNION ALL
+		    /*CARDIF SPF*/
+		    SELECT DISTINCT * FROM tbbvseg 
+		      WHERE cdseguradora IN (109719 /*CARDIF*/)
+		          AND extract(year from dtprocessamento)>=2026
+					AND extract(month from dtprocessamento) >=2
+						AND extract(day from dtprocessamento) >=12
 		  )
```


## Consignado_PF_INSS v7.egp  -  Cobranças vs Negócios Transacionais Varejo e NaPista


### CodeTask-kEtlYtmrEe2ZeKbT  (+3/-3)
```diff
@@ -10,5 +10,5 @@
 
-%LET SAFRA = 202603; 			
-%LET DT_INICIAL = '2026-03-01'; 	
-%LET DT_FINAL = '2026-03-31'; 	
+%LET SAFRA = 202511; 			
+%LET DT_INICIAL = '2025-11-01'; 	
+%LET DT_FINAL = '2025-11-30'; 	
 
```


## GeraBaseOperacoesPLRC.egp  -  Atacado vs Crédito


### CodeTask-L7P2cLpdj4lsfrfK  (+1/-13)
```diff
@@ -120,11 +120,2 @@
 where flever60 = 1 and safraref = &a00. 
-group by 1
-;run;
-
-proc sql;
-create table tbindicadores_ever90_desembolso as select
- safradesembolso as safra
-,sum(vroperacao) as vrever90_desembolso
-from tbconsolidada_safra
-where flever90 = 1 and safraref = &a00. 
 group by 1
@@ -283,3 +274,2 @@
 ,case when b24.vrever60_desembolso     = . then 0 else b24.vrever60_desembolso     end as vrever60_desembolso
-,case when b25.vrever90_desembolso     = . then 0 else b25.vrever90_desembolso     end as vrever90_desembolso
 
@@ -312,3 +302,2 @@
 left join tbindicadores_ever60_desembolso     as b24 on a.safra = b24.safra
-left join tbindicadores_ever90_desembolso     as b25 on a.safra = b25.safra
 
@@ -371,4 +360,3 @@
 		  t1.vrover90_desembolso as vrorigover90,
-		  t1.vrever60_desembolso as vrorigever60,
-		  t1.vrever90_desembolso as vrorigever90,
+		  t1.vrever60_desembolso as vrorigover60,
 		  t1.vrorigavencer,
```


## SPF.egp  -  Negócios e Produtos Relacional e Seguros vs Seguros


### CodeTask-yNMrQYpfhIu63w2l  (+1/-1)
```diff
@@ -9,3 +9,3 @@
 
-	select @vinicio = today()-360 /*700*
+	select @vinicio = '2024-11-01'
 /*	select @vtermino = dateadd(second,-1,convert(char(10), getdate(), 23))*/
```


## [Gestão_de_Carteira] Motores.egp  -  Atacado vs Crédito


### CodeTask-3oRIhLP4NADgi8Bn  (+2/-78)
```diff
@@ -42,73 +42,2 @@
 PROC SQL;
-    CONNECT TO SYBASE (SERVER=MORSYBCTR USER=&U_CTR PASSWORD=<REDACTED>
-
-    CREATE TABLE GRUPO_SUSPENSO AS
-    SELECT * FROM CONNECTION TO SYBASE (
-        SELECT DISTINCT
-            A.CdGrupoEconomico,
-            B.CdPessoa,
-			C.NuCpfCnpj,
-			'GRUPO' AS ARRASTO_SUSPENSAO,
-			E.NmTipoSuspensaoLimite,
-			CONVERT(DATE, A.DtAtivacaoSuspensao) AS DtAtivacaoSuspensao
-		FROM DBGERENCIADORLIMITE..TbSuspensaoLimite AS A
-        LEFT JOIN DBGLOBAL..TbPessoaGrupoEconomico AS B ON A.CdGrupoEconomico = B.CdGrupoEconomico
-		LEFT JOIN DBGLOBAL..TBPESSOA AS C ON B.CDPESSOA = C.CDPESSOA
-		LEFT JOIN DBGERENCIADORLIMITE..TBMOTIVOSUSPENSAO AS D ON A.CdSuspensaoLimite = D.CdSuspensaoLimite
-		LEFT JOIN DBGERENCIADORLIMITE..TBTIPOSUSPENSAOLIMITE AS E ON D.CdTipoSuspensaoLimite = E.CdTipoSuspensaoLimite
-        WHERE A.FlAtivo = 'S' and A.CdGrupoEconomico IS NOT NULL
-    );
-
-    DISCONNECT FROM SYBASE;
-QUIT;
-
-PROC SQL;
-    CONNECT TO SYBASE (SERVER=MORSYBCTR USER=&U_CTR PASSWORD=<REDACTED>
-
-    CREATE TABLE CLINTE_SUSPENSO AS
-    SELECT * FROM CONNECTION TO SYBASE (
-        SELECT DISTINCT
-			C.CdGrupoEconomico,
-            A.CdPessoa,
-			B.NuCpfCnpj,
-			'CLIENTE' AS ARRASTO_SUSPENSAO,
-			E.NmTipoSuspensaoLimite,
-			CONVERT(DATE, A.DtAtivacaoSuspensao) AS DtAtivacaoSuspensao
-		FROM DBGERENCIADORLIMITE..TbSuspensaoLimite A
-		LEFT JOIN DBGLOBAL..TBPESSOA AS B ON A.CDPESSOA = B.CDPESSOA
-		LEFT JOIN DBGLOBAL..TbPessoaGrupoEconomico AS C ON A.CDPESSOA = C.CDPESSOA
-		LEFT JOIN DBGERENCIADORLIMITE..TBMOTIVOSUSPENSAO AS D ON A.CdSuspensaoLimite = D.CdSuspensaoLimite
-		LEFT JOIN DBGERENCIADORLIMITE..TBTIPOSUSPENSAOLIMITE AS E ON D.CdTipoSuspensaoLimite = E.CdTipoSuspensaoLimite
-        WHERE A.FlAtivo = 'S' and A.CdGrupoEconomico IS NULL 
-    );
-
-    DISCONNECT FROM SYBASE;
-QUIT;
-
-DATA BASE_SUSPENSAO;
-SET CLINTE_SUSPENSO GRUPO_SUSPENSO;
-RUN;
-
-	proc sort data=BASE_SUSPENSAO;
-    by descending CdPessoa ;
-	run;
-
-	data PME.BASE_SUSPENSAO_GL;
-    set BASE_SUSPENSAO;
-    by descending CdPessoa ;
-    if first.CdPessoa;
-	run;
... (+33 linhas, ver no arquivo completo)
```


### CodeTask-5A8HQGwO6eb5qi8B  (+8/-9)
```diff
@@ -10,11 +10,10 @@
 LIBNAME PME         '/riscosbv/credito/SME'                           ;
-LIBNAME PLCA        '/riscosbv/credito/rgustavo/ESTRATEGIA/SME/PLCA';  
-LIBNAME SME 		'/riscosbv/credito/rgustavo/ESTRATEGIA/SME'       ;
-LIBNAME MISCRED		'/riscosbv/credito/MISCREDITO'                   ;
-LIBNAME INSIGHT 	'/riscosbvf/insight';                              
-LIBNAME _INSIGHT 	'/riscosbvf/insight'; 
-LIBNAME SHAREATA 	'/riscosbvf/plan_mesas/shared/atacado'            ;
-LIBNAME ATACADO		'/riscosbvf/gbinfra/atacado'                      ;
-LIBNAME GCSERASA 	'/riscosbvf/insight/GCarteira'                    ; 
-LIBNAME SOCIOS 		'/riscosbvf/plan_mesas/comp_total'                ;
+LIBNAME PLCA        '/riscosbv/credito/rgustavo/ESTRATEGIA/SME/PLCA'  ACCESS = READONLY;
+LIBNAME SME 		'/riscosbv/credito/rgustavo/ESTRATEGIA/SME'       ACCESS = READONLY;
+LIBNAME MISCRED		'/riscosbv/credito/MISCREDITO'                    ACCESS = READONLY;
+LIBNAME INSIGHT 	'/riscosbvf/insight'                              ACCESS = READONLY;
+LIBNAME SHAREATA 	'/riscosbvf/plan_mesas/shared/atacado'            ACCESS = READONLY;
+LIBNAME ATACADO		'/riscosbvf/gbinfra/atacado'                      ACCESS = READONLY;
+LIBNAME GCSERASA 	'/riscosbvf/insight/GCarteira'                    ACCESS = READONLY; 
+LIBNAME SOCIOS 		'/riscosbvf/plan_mesas/comp_total'                ACCESS = READONLY;
 
```


### CodeTask-FqR1JApMcvYeNlv2  (+163/-401)
```diff
@@ -7,172 +7,100 @@
 
-
-	
 PROC SQL;
-    CREATE TABLE BASE_MONITORAMENTO_AUX AS
-    SELECT
-        TODAY() AS DT_MONITORAMENTO FORMAT=DATE9.,
-        *,
-        
-        /* VNP */
-        (CASE 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 5 AND 10  THEN 2 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 11 AND 14 THEN 5 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 15 AND 89 THEN 10 
-            WHEN QTD_TOT_DIA_ATR_M00 >= 90 THEN 100 
-            ELSE 0 
-         END) AS Pontos_VNP,
-        (CASE 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 5 AND 10  THEN 'poucos dias em atraso' 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 11 AND 14 THEN 'entre 11 e 14 dias em atraso' 
-            WHEN QTD_TOT_DIA_ATR_M00 BETWEEN 15 AND 89 THEN 'em atraso' 
-            WHEN QTD_TOT_DIA_ATR_M00 >= 90 THEN 'muitos dias em atraso' 
-            ELSE '' 
-         END) AS texto_VNP,
-
-        /* PRINAD (pontos) */
-        (CASE 
-            WHEN TIPO NE 'OMIE' AND PRINAD_FINAL > 10 THEN 10 
-            WHEN TIPO IN ('COBAN') 
-                 AND MODELO_PRINAD IN ('Modelo HBV8 Serasa         ', 'Modelo HPJ8 Serasa         ') 
-                 AND PRINAD_FINAL > 10 THEN 10  
-            WHEN TIPO IN ('INDUSTRIA', 'Indústria') 
-                 AND MODELO_PRINAD = 'Modelo HBV8 Serasa         '  
-                 AND PRINAD_FINAL > 5 THEN 5  
-            WHEN TIPO IN ('AGRO', 'Agro') 
-                 AND MODELO_PRINAD = 'Modelo HBV8 Serasa         ' 
-                 AND PRINAD_FINAL > 3 THEN 5  
-            WHEN MODELO_PRINAD = 'Modelo CIB Vigente         ' 
-                 AND TIPO NE 'OMIE' 
-                 AND PRINAD_FINAL >= 2 THEN 10 
-            WHEN MODELO_PRINAD = 'Modelo Quanti CIB Calculado' 
-                 AND TIPO NE 'OMIE' 
-                 AND PRINAD_FINAL >= 3 THEN 10 
-            WHEN MODELO_PRINAD = 'Modelo Quanti CIB Calculado' 
-                 AND TIPO NE 'OMIE' 
-                 AND PRINAD_FINAL >= 2 
-                 AND PRINAD_HPJ8 >= 3 THEN 10 
-            WHEN TIPO NOT IN ('COBAN') 
-                 AND TIPO NE 'OMIE' 
-                 AND MODELO_PRINAD = 'Modelo HPJ8 Serasa         ' 
-                 AND PRINAD_FINAL >= 5 THEN 5  
-            ELSE 0 
-         END) AS PONTOS_PRINAD_INICIAL,
-
-        /* PRINAD (texto) */
-        (CASE 
-            WHEN TIPO NE 'OMIE' AND PRINAD_FINAL > 10 THEN 
-                CATX(' ', 'prinad final de', CATX('', ROUND(PRINAD_FINAL, 0.1), '%'))
-            WHEN TIPO IN ('COBAN') 
... (+523 linhas, ver no arquivo completo)
```


### CodeTask-HcM4dxe8Pl9BxvfH  (+6/-7)
```diff
@@ -67,9 +67,8 @@
 	
-
    		'OMIE' AS TIPO 									LENGTH = 50,
-		'' AS NOME_SACADO								LENGTH = 200,
-		'01JAN2025'd AS DT_ESTEIRA format ddmmyy10.		LENGTH = 8,
+		NomeCedente AS NOME_SACADO						LENGTH = 200,
+		DtProcessamento AS DT_ESTEIRA					LENGTH = 8,
 		''  as PORTFOLIO								LENGTH = 100, 
 		121 as ID_PROGRAMA_PLCA							LENGTH = 8,
-		DOC_RAIZ AS CNPJ_RAIZ_SACADO					LENGTH = 20,
+		SUBSTR(CNPJCedente,1,8) AS CNPJ_RAIZ_SACADO		LENGTH = 20,
 		'MONITORAMENTO' AS ESTEIRA 						LENGTH = 50
@@ -77,5 +76,5 @@
 
-      FROM PLCA.TBSISTEMAPLCA WHERE ID_PROGRAMA_PLCA = 121 AND STATUS_RAIZ IN ('Ativo','Inativo') AND LIMITE_CREDITO_RAIZ_NO_PROGRAMA > 0
-
-	  ORDER BY DOC_RAIZ DESC
+      FROM PME.BASE_HISTORICA_OMIE_CEDENTES
+      WHERE FlagVigente = 1 AND DecisaoFinal = 'Elegível'
+	  ORDER BY DtProcessamento DESC
 ;QUIT;
```


### CodeTask-JgKtUo8b2lhLJGbZ  (+2/-2)
```diff
@@ -16,3 +16,3 @@
 
-	LEFT JOIN PME.BASE_FATURAMENTO_SERASA_PJ AS B
+	LEFT JOIN PME.BASE_FATURAMENTO_SERASA_PJ_2025 AS B
 
@@ -31,3 +31,3 @@
 
-	LEFT JOIN PME.BASE_FATURAMENTO_SERASA_PJ AS B
+	LEFT JOIN PME.BASE_FATURAMENTO_RAIZ_2025 AS B
 
```


### CodeTask-Jmmz2PktxedShhJB  (+1/-1)
```diff
@@ -33,3 +33,3 @@
 
-	FROM PME.BASE_BALANCO_SERASA_PJ;
+	FROM PME.BASE_BALANCO_SERASA_PJ_2024;
 
```


### CodeTask-KcdP4qv2VNJAiyk4  (+5/-5)
```diff
@@ -31,3 +31,3 @@
 		  case when t1.obs contains ('CNPJ sem informação') then 1 else 0 end as flag_delete
-      FROM pme.TBMGCANALITICA t1
+      FROM INSIGHT.TBMGCANALITICA t1
       WHERE t1.FlAtual = 1
@@ -47,3 +47,3 @@
 
-	FROM PME.TBMGCANALITICA AS A
+	FROM _INSIGHT.TBMGCANALITICA AS A
 	LEFT JOIN BLOQUEADOS_PLCA AS B ON(A.CNPJ_RAIZ_SACADO = B.DOC_RAIZ)
@@ -70,7 +70,7 @@
 		case when CATX(' | ',A.CLASS_MGC,A.OBS) eq '' then 'MGC' else CATX(' | ',A.CLASS_MGC,A.OBS) end AS 'Descrição'N LENGHT = 99,
-		"Não" AS 'Temporária'N,
-		. FORMAT= DDMMYY10. AS 'Data Final'N,
+		"Sim" AS 'Temporária'N,
+		'31dec2030'd FORMAT= DDMMYY10. AS 'Data Final'N,
 		'Inclusão' as 'Ação'n
 
-	FROM PME.TBMGCANALITICA AS A
+	FROM _INSIGHT.TBMGCANALITICA AS A
 	LEFT JOIN DESBLOQUEADOS_PLCA AS B ON(A.CNPJ_RAIZ_SACADO = B.DOC_RAIZ)
```


### CodeTask-Nj3getTjpUpO5dL7  (+1/-1)
```diff
@@ -14,3 +14,3 @@
 
-	FROM PME.BASE_CADASTRAL_SERASA_PJ AS A
+	FROM INSIGHT.BASE_CADASTRAL_SERASA_PJ_2025 AS A
 	
```


### CodeTask-WiPLSiZZjRgW9ekx  (+1/-1)
```diff
@@ -44,3 +44,3 @@
 DATA TBCARTEIRAGRUPOHIST;
-SET INSIGHT.TBCARTEIRAGRUPOHIST;
+SET PME.TBCARTEIRAGRUPOHIST;
 IF FLAG_ATUAL = 1;
```


### CodeTask-XgF7kB8jqBWOu6Tb  (+7/-7)
```diff
@@ -19,4 +19,4 @@
 		,MAX(FlAtivoGP) AS FLAG_ATIVO_GRUPO
-/*		,MAX(FlSuspensoP) AS FLAG_SUSPENSO_CLIENTE*/
-/*		,MAX(FlSuspensoGrupo) AS FLAG_SUSPENSO_GRUPO*/
+		,MAX(FlSuspensoP) AS FLAG_SUSPENSO_CLIENTE
+		,MAX(FlSuspensoGrupo) AS FLAG_SUSPENSO_GRUPO
 		,MAX(DtVencimentoRiscoCreditoGLGrupo) AS DAT_VENC_GRUPO FORMAT = DDMMYY10.
@@ -132,4 +132,4 @@
 	   		WHEN B.PRIORIDADE NE 1 THEN 0 ELSE 1 END AS FLAG_CADASTRO_CIB
-/*	   ,CASE WHEN B.FLAG_SUSPENSO_CLIENTE = . THEN -1 ELSE B.FLAG_SUSPENSO_CLIENTE END AS FLAG_SUSPENSO_CLIENTE*/
-/*	   ,CASE WHEN B.FLAG_SUSPENSO_GRUPO = . THEN -1 ELSE B.FLAG_SUSPENSO_GRUPO END AS FLAG_SUSPENSO_GRUPO*/
+	   ,CASE WHEN B.FLAG_SUSPENSO_CLIENTE = . THEN -1 ELSE B.FLAG_SUSPENSO_CLIENTE END AS FLAG_SUSPENSO_CLIENTE
+	   ,CASE WHEN B.FLAG_SUSPENSO_GRUPO = . THEN -1 ELSE B.FLAG_SUSPENSO_GRUPO END AS FLAG_SUSPENSO_GRUPO
 	   ,CASE WHEN B.DAT_VENC_GRUPO = . THEN '09SEP9999'd ELSE B.DAT_VENC_GRUPO END AS DAT_VENC_GRUPO FORMAT = DATE9.
@@ -162,4 +162,4 @@
 
-/*PROC DELETE DATA = BASE_MONITORAMENTO_1 */
-/*                   BASE_MONITORAMENTO_2; */
-/*RUN;*/
+PROC DELETE DATA = BASE_MONITORAMENTO_1 
+                   BASE_MONITORAMENTO_2; 
+RUN;
```


### CodeTask-eC9dMbr1Y7sP4oDg  (+1/-1)
```diff
@@ -17,3 +17,3 @@
 
-	FROM 	PME.BASE_CADASTRAL_SERASA_PJ;
+	FROM INSIGHT.BASE_CADASTRAL_SERASA_PJ_2025;
 
```


### CodeTask-jWaCwsXj7a2giB8n  (+24/-24)
```diff
@@ -81,3 +81,3 @@
 
-		CASE WHEN A.CNPJ_RAIZ IS NULL THEN B.NuCnpjRaiz ELSE A.CNPJ_RAIZ END AS CNPJ_RAIZ,
+		A.CNPJ_RAIZ,
 		CASE WHEN B.NuCnpjRaiz IS NOT NULL THEN B.QdComercial ELSE A.QTD_RESTRITIVOS END AS QTD_RESTRITIVOS,
@@ -87,3 +87,3 @@
 	FROM BASE_RESTRITIVO_1 AS A
-	FULL JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
+	LEFT JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
 ;QUIT;
@@ -106,3 +106,3 @@
 
-		CASE WHEN A.CNPJ_RAIZ IS NULL THEN B.NuCnpjRaiz ELSE A.CNPJ_RAIZ END AS CNPJ_RAIZ,
+		A.CNPJ_RAIZ,
 		CASE WHEN B.NuCnpjRaiz IS NOT NULL THEN B.QdconcordatafalenRJ ELSE A.QTD_FALENCIA END AS QTD_FALENCIA
@@ -110,3 +110,3 @@
 	FROM BASE_RESTRITIVO_2 AS A
-	FULL JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
+	LEFT JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
 ;QUIT;
@@ -129,3 +129,3 @@
 
-		CASE WHEN A.CNPJ_RAIZ IS NULL THEN B.NuCnpjRaiz ELSE A.CNPJ_RAIZ END AS CNPJ_RAIZ,
+		A.CNPJ_RAIZ,
 		CASE WHEN B.NuCnpjRaiz IS NOT NULL THEN B.QdRefin ELSE A.QTD_REFIN END AS QTD_REFIN
@@ -133,3 +133,3 @@
 	FROM BASE_RESTRITIVO_3 AS A
-	FULL JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
+	LEFT JOIN TbPMESerasa AS B ON(A.CNPJ_RAIZ = B.NuCnpjRaiz)
 ;QUIT;
@@ -145,9 +145,9 @@
 			ELSE 12000 END AS VLR_FATUR_FINAL
-		   ,CASE WHEN B1.QTD_RESTRITIVOS IN (. 0) THEN 0 ELSE B1.QTD_RESTRITIVOS END AS QTD_RESTRITIVOS
-		   ,CASE WHEN B1.VLR_RESTRITIVOS IN (. 0) THEN 0 ELSE B1.VLR_RESTRITIVOS END AS VLR_RESTRITIVOS
-		   ,CASE WHEN B1.VLR_RESTRITIVOS IN (. 0) THEN 0 
+		   ,CASE WHEN B1.QTD_RESTRITIVOS = . THEN 0 ELSE B1.QTD_RESTRITIVOS END AS QTD_RESTRITIVOS
+		   ,CASE WHEN B1.VLR_RESTRITIVOS = . THEN 0 ELSE B1.VLR_RESTRITIVOS END AS VLR_RESTRITIVOS
+		   ,CASE WHEN B1.VLR_RESTRITIVOS = . THEN 0 
 		         WHEN B1.VLR_RESTRITIVOS/(CALCULATED VLR_FATUR_FINAL/12) >= 0.2 THEN 1
 			ELSE 0 END AS FLAG_RESTRITIVOS
-		   ,CASE WHEN B2.QTD_FALENCIA IN (. 0) THEN 0 ELSE 1 END AS FLAG_FALENCIA
-		   ,CASE WHEN B3.QTD_REFIN IN (. 0) THEN 0 ELSE 1 END AS FLAG_REFIN
+		   ,CASE WHEN B2.QTD_FALENCIA = . THEN 0 ELSE 1 END AS FLAG_FALENCIA
+		   ,CASE WHEN B3.QTD_REFIN = . THEN 0 ELSE 1 END AS FLAG_REFIN
 
@@ -161,14 +161,14 @@
 /**/
-/*PROC DELETE DATA = */
-/*                   BASE_RESTRITIVO_1*/
-/*				   BASE_RESTRITIVO_11*/
-/*				   BASE_RESTRITIVO_2*/
-/*				   BASE_RESTRITIVO_22*/
-/*				   BASE_RESTRITIVO_3*/
-/*				   BASE_RESTRITIVO_33*/
-/*				   TbOcorrencias*/
-/*					TbDtUltMovimento*/
-/*					TbPMESerasa*/
-/* */
-/*;RUN;*/
-/**/
... (+13 linhas, ver no arquivo completo)
```


### CodeTask-mvzMG9GcL2op7zPl  (+1/-6)
```diff
@@ -123,3 +123,3 @@
         %put A tabela &dataset não está vazia. Executando o processo...;
-        data PME.TBMGCANALITICA;
+        data _INSIGHT.TBMGCANALITICA;
             set TBMGCANALITICA_;
@@ -136,6 +136 @@
 %verifica_e_processa(dataset=TBMGCANALITICA_);
-
-/*data PME.TBMGCANALITICA;*/
-/*set  PME.TBMGCANALITICA;*/
-/*	if DT_MONITORAMENTO eq '06JAN2026'd then delete;*/
-/*run;*/
```
