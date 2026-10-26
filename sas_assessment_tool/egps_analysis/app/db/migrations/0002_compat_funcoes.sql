-- Funções e tipos com nome e semântica do Spark SQL, no schema compat (ADR 0005, Fase 1).
--
-- Na Fase 1 o mesmo SQL do backend roda no Databricks e no Postgres. O app conecta com
-- search_path = compat, derivado, pg_catalog, public: como compat vem ANTES de pg_catalog,
-- uma função daqui com a mesma assinatura de uma do sistema a SOMBREIA (verificado no PG 17).
-- Só entra aqui o que o backend usa de fato; o que não dá para imitar (current_timestamp()
-- com parênteses, lambda, ARRAY literal) é reescrito no código para a forma que roda nos dois.
-- Some na Fase 2, quando o SQL passa a ser só Postgres.

-- CAST(x AS STRING) / CAST(x AS DOUBLE)
CREATE DOMAIN compat.string AS text;
CREATE DOMAIN compat.double AS double precision;

-- split(str, regex) -> array (Spark usa regex no separador, como regexp_split_to_array)
CREATE FUNCTION compat.split(text, text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$ SELECT regexp_split_to_array($1, $2) $$;

-- explode(array) no SELECT -> uma linha por elemento
CREATE FUNCTION compat.explode(anyarray) RETURNS SETOF anyelement
LANGUAGE sql IMMUTABLE AS $$ SELECT unnest($1) $$;

-- element_at(array, n): índice a partir de 1 nos DOIS bancos (no Spark, arr[0] é base 0 e
-- no Postgres arr[1] é base 1 — por isso o código usa element_at, nunca colchete)
CREATE FUNCTION compat.element_at(anyarray, integer) RETURNS anyelement
LANGUAGE sql IMMUTABLE AS $$ SELECT $1[$2] $$;

CREATE FUNCTION compat.array_contains(anyarray, anyelement) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$ SELECT $2 = ANY($1) $$;

CREATE FUNCTION compat.arrays_overlap(anyarray, anyarray) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$ SELECT $1 && $2 $$;

CREATE FUNCTION compat.size(anyarray) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT coalesce(cardinality($1), -1) $$;

-- regexp_replace do Spark troca TODAS as ocorrências; o do Postgres só a primeira sem 'g'
CREATE FUNCTION compat.regexp_replace(text, text, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT pg_catalog.regexp_replace($1, $2, $3, 'g') $$;

-- count_if(cond)
CREATE FUNCTION compat._count_if_passo(bigint, boolean) RETURNS bigint
LANGUAGE sql IMMUTABLE AS $$ SELECT $1 + CASE WHEN $2 THEN 1 ELSE 0 END $$;
CREATE AGGREGATE compat.count_if(boolean) (SFUNC = compat._count_if_passo, STYPE = bigint, INITCOND = '0');

-- from_utc_timestamp(ts, tz): o instante visto no fuso tz (sem fuso no resultado)
CREATE FUNCTION compat.from_utc_timestamp(timestamptz, text) RETURNS timestamp
LANGUAGE sql STABLE AS $$ SELECT $1 AT TIME ZONE $2 $$;

-- date_format(ts, padrão Java) — só os pedaços que o backend usa (yyyy, MM, dd, HH, mm, ss)
CREATE FUNCTION compat._padrao_java(text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT replace(replace(replace(replace(replace(replace($1,
         'yyyy', 'YYYY'), 'dd', 'DD'), 'HH', 'HH24'), 'mm', 'MI'), 'ss', 'SS'), 'MM', 'MM')
$$;
CREATE FUNCTION compat.date_format(timestamptz, text) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
CREATE FUNCTION compat.date_format(timestamp, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
CREATE FUNCTION compat.date_format(date, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
