#!/usr/bin/env bash
# publica_arquivos.sh — publica arquivos do servidor SAS num lugar de onde outras
# pessoas possam pegá-los.
#
# RODA DENTRO DO SERVIDOR SAS (via ssh). Só lê a origem; nunca escreve nela.
#
#   ssh int.ldacol@srv-sasprd04n1 'bash -s' < publica_arquivos.sh -- --detect
#   ./publica_arquivos.sh --dest ~/publicado /riscosbv/cobranca/erocha/mis_cl_pagto.sas7bdat
#   ./publica_arquivos.sh --dest ~/publicado --tar --lista caminhos.txt
#
# Por que "publicar" e não "copiar": além de copiar, ele gera MANIFESTO.tsv com
# sha256/tamanho/mtime/dono de cada arquivo, para quem receber conferir integridade e
# saber de onde veio. Sem isso um .sas7bdat solto numa pasta é indistinguível de uma
# cópia velha — que é exatamente o problema que estamos mapeando na migração.
#
# Compatibilidade: o SO dos nós não foi confirmado (Linux/AIX), então toda ferramenta
# não-POSIX entra por cascata de fallback e a ausência é REPORTADA, nunca silenciosa.

set -u

PROG=$(basename "$0")
DEST=""
FAZ_TAR=0
SO_DETECTA=0
FORCA=0
GRUPO=""
LISTA=""
ALVOS=()

# Raízes de produção: o destino NUNCA pode cair dentro delas.
RAIZES_PROD="/riscosbv /riscosbvf /infogrc /projetos /financas /seguros /regulatorio /ouvidoria /portfoliomis /digital /bancodigital /neon /auditoria /atendimento /miscomercial"

uso() {
    cat <<TXT
Uso: $PROG [opções] <caminho> [caminho...]

  --dest DIR       diretório de publicação (obrigatório, exceto com --detect)
  --lista ARQ      lê caminhos de um arquivo, um por linha (aceita # comentário)
  --grupo GRP      chgrp do destino + chmod g+rX, para o grupo poder pegar
  --tar            empacota tudo num .tar.gz único (manifesto fica fora, legível)
  --detect         só reporta as rotas de saída disponíveis e sai
  --forca          permite destino dentro de raiz de produção (NÃO use)
  -h, --help       esta ajuda

Caminho pode ser arquivo ou diretório (diretório é copiado recursivamente).
TXT
}

log()  { printf '%s\n' "$*" >&2; }
erro() { printf 'ERRO: %s\n' "$*" >&2; }

tem() { command -v "$1" >/dev/null 2>&1; }

# Normaliza um caminho resolvendo "." e ".." LEXICAMENTE (sem tocar no filesystem — o
# destino pode nem existir ainda). Puro bash, funciona igual pra relativo ou absoluto:
# não depende de `realpath`/`readlink -f` (GNU-only, pode faltar no nó — SO não
# confirmado, ver nota de compatibilidade no topo). Existe porque o guard de
# produção mais abaixo casa DEST_ABS por PREFIXO de string contra RAIZES_PROD — um
# "--dest /home/x/../../riscosbv/y" não muda o prefixo textual, mas o `mkdir`/`cp`
# resolvem o ".." de verdade depois, escrevendo dentro da raiz que o guard existe
# pra proteger.
normaliza_caminho() {
    local entrada="$1" abs part n=0
    case "$entrada" in
        /*) abs="$entrada" ;;
        *)  abs="$PWD/$entrada" ;;
    esac
    local partes
    IFS='/' read -ra partes <<< "$abs"
    local out=()
    for part in "${partes[@]}"; do
        case "$part" in
            ""|".") continue ;;
            "..") [ "$n" -gt 0 ] && n=$((n - 1)) ;;
            *) out[$n]="$part"; n=$((n + 1)) ;;
        esac
    done
    local resultado="" i
    for (( i = 0; i < n; i++ )); do
        resultado="$resultado/${out[$i]}"
    done
    printf '%s\n' "${resultado:-/}"
}

# ---------- parse ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --dest)   DEST="${2:-}"; shift 2 ;;
        --lista)  LISTA="${2:-}"; shift 2 ;;
        --grupo)  GRUPO="${2:-}"; shift 2 ;;
        --tar)    FAZ_TAR=1; shift ;;
        --detect) SO_DETECTA=1; shift ;;
        --forca)  FORCA=1; shift ;;
        -h|--help) uso; exit 0 ;;
        --) shift ;;
        -*) erro "opção desconhecida: $1"; uso; exit 2 ;;
        *)  ALVOS[${#ALVOS[@]}]="$1"; shift ;;
    esac
done

# ---------- detecção de ambiente ----------
NO=$(hostname 2>/dev/null || echo '?')

soma_sha() {
    # Cascata: GNU -> perl-ish -> openssl -> cksum (fraco, avisa).
    if   tem sha256sum; then sha256sum "$1" 2>/dev/null | awk '{print $1}'
    elif tem shasum;    then shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
    elif tem openssl;   then openssl dgst -sha256 "$1" 2>/dev/null | awk '{print $NF}'
    elif tem cksum;     then printf 'cksum:%s' "$(cksum "$1" 2>/dev/null | awk '{print $1}')"
    else printf 'sem-checksum'
    fi
}

meta_arquivo() {
    # tamanho<TAB>mtime<TAB>dono<TAB>grupo<TAB>modo — GNU stat, senão parse do ls -ld.
    if tem stat && stat -c '%s' "$1" >/dev/null 2>&1; then
        stat -c '%s	%y	%U	%G	%A' "$1" 2>/dev/null
    else
        ls -ld "$1" 2>/dev/null | awk '{print $5 "\t" $6" "$7" "$8 "\t" $3 "\t" $4 "\t" $1}'
    fi
}

detecta() {
    log "== nó: $NO"
    log "== ferramentas"
    for t in sha256sum shasum openssl tar gzip python3 python gsutil gcloud databricks curl rsync; do
        if tem "$t"; then log "   ok      $t"; else log "   ausente $t"; fi
    done
    log "== mounts que podem servir de saída (cifs/smb/nfs/gcs)"
    if tem mount; then
        mount 2>/dev/null | grep -iE 'cifs|smb|gcsfuse|fuse|nfs' | sed 's/^/   /' >&2 \
            || log "   (nenhum)"
    else
        log "   comando mount indisponível"
    fi
    log "== /mnt e /media"
    ls -1 /mnt /media 2>/dev/null | sed 's/^/   /' >&2 || log "   (vazio/inexistente)"
    log "== saída para internet (5s)"
    if tem curl && curl -sS -m 5 -o /dev/null https://storage.googleapis.com 2>/dev/null; then
        log "   ok — o servidor alcança a internet (gsutil/gcloud viáveis)"
    else
        log "   sem saída direta (ou curl ausente) — publique localmente e puxe por scp"
    fi
    log "== home compartilhado entre nós?"
    log "   HOME=$HOME"
    if tem mount && mount 2>/dev/null | grep -q " ${HOME%/*} .*nfs"; then
        log "   home parece ser NFS (provavelmente visível dos 3 nós)"
    else
        log "   não confirmado — se for local, um arquivo publicado aqui NÃO aparece nos outros nós"
    fi
    log "   ATENÇÃO: /tmp é por nó. Nunca publique em /tmp para outra pessoa pegar."
}

if [ "$SO_DETECTA" -eq 1 ]; then
    detecta
    exit 0
fi

# ---------- validação ----------
[ -n "$DEST" ] || { erro "--dest é obrigatório"; uso; exit 2; }

if [ -n "$LISTA" ]; then
    [ -r "$LISTA" ] || { erro "lista ilegível: $LISTA"; exit 2; }
    while IFS= read -r ln; do
        case "$ln" in ''|\#*) continue ;; esac
        ALVOS[${#ALVOS[@]}]="$ln"
    done < "$LISTA"
fi

[ "${#ALVOS[@]}" -gt 0 ] || { erro "nenhum caminho informado"; uso; exit 2; }

# destino não pode ficar dentro de produção — um output acidental ali é escrita em prod.
# normaliza_caminho resolve ".." lexicamente pros dois casos (relativo/absoluto) — ver
# o comentário na definição da função para o porquê de não usar só `cd ... && pwd`
# (isso não canonicalizava caminho absoluto, e falhava mudo se o pai ainda não existe).
DEST_ABS="$(normaliza_caminho "$DEST")"
for raiz in $RAIZES_PROD; do
    case "$DEST_ABS/" in
        "$raiz"/*)
            if [ "$FORCA" -eq 1 ]; then
                log "AVISO: destino dentro de produção ($raiz) — seguindo por --forca"
            else
                erro "destino $DEST_ABS está dentro da raiz de produção $raiz."
                erro "Publique no seu home (ex.: --dest \$HOME/publicado). Use --forca só se souber o que faz."
                exit 3
            fi
            ;;
    esac
done
case "$DEST_ABS" in
    /tmp|/tmp/*) log "AVISO: /tmp é por nó ($NO). Outras pessoas só pegam se estiverem NESTE nó." ;;
esac

mkdir -p "$DEST_ABS/dados" || { erro "não consegui criar $DEST_ABS"; exit 3; }
MAN="$DEST_ABS/MANIFESTO.tsv"
# APPEND, nunca truncate: re-rodar o lote não pode apagar o registro do que já foi
# publicado (o manifesto é a prova de procedência de arquivos que já saíram daqui).
# RUN identifica a execução para separar as linhas de cada rodada.
RUN="$(date +%Y%m%d_%H%M%S)_${NO}_$$"
if [ ! -f "$MAN" ]; then
    printf 'run\torigem\tdestino\tbytes\tmtime\tdono\tgrupo\tmodo\tsha256\tstatus\n' > "$MAN"
fi

# ---------- cópia ----------
copiados=0; pulados=0; falhas=0

publica_um() {
    src="$1"
    base=$(basename "$src")
    dst="$DEST_ABS/dados/$base"
    if [ ! -r "$src" ]; then
        printf '%s\t%s\t\t\t\t\t\t\t\tILEGIVEL\n' "$RUN" "$src" >> "$MAN"
        erro "ilegível (permissão ou inexistente): $src"
        falhas=$((falhas+1))
        return
    fi
    sha=$(soma_sha "$src")
    # idempotência: mesmo nome e mesmo checksum = já publicado
    if [ -f "$dst" ] && [ "$(soma_sha "$dst")" = "$sha" ]; then
        printf '%s\t%s\t%s\t%s\t%s\tJA_PUBLICADO\n' "$RUN" "$src" "$dst" "$(meta_arquivo "$src")" "$sha" >> "$MAN"
        pulados=$((pulados+1))
        return
    fi
    if cp -p "$src" "$dst" 2>/dev/null || cp "$src" "$dst" 2>/dev/null; then
        printf '%s\t%s\t%s\t%s\t%s\tOK\n' "$RUN" "$src" "$dst" "$(meta_arquivo "$src")" "$sha" >> "$MAN"
        copiados=$((copiados+1))
    else
        printf '%s\t%s\t%s\t\t\t\t\t\t%s\tFALHA_COPIA\n' "$RUN" "$src" "$dst" "$sha" >> "$MAN"
        erro "falha ao copiar: $src"
        falhas=$((falhas+1))
    fi
}

for alvo in "${ALVOS[@]}"; do
    if [ -d "$alvo" ]; then
        # diretório: copia recursivo preservando a subárvore sob dados/<nome>
        nome=$(basename "$alvo")
        if tem rsync; then
            rsync -a --no-owner --no-group "$alvo/" "$DEST_ABS/dados/$nome/" 2>/dev/null \
                && log "dir  OK   $alvo -> dados/$nome/" \
                || { erro "falha no rsync de $alvo"; falhas=$((falhas+1)); }
        else
            mkdir -p "$DEST_ABS/dados/$nome" \
                && cp -R "$alvo/." "$DEST_ABS/dados/$nome/" 2>/dev/null \
                && log "dir  OK   $alvo -> dados/$nome/ (cp -R)" \
                || { erro "falha ao copiar dir $alvo"; falhas=$((falhas+1)); }
        fi
        # manifesto por arquivo dentro do dir
        find "$alvo" -type f 2>/dev/null | while IFS= read -r f; do
            printf '%s\t%s\t%s\t%s\t%s\tOK_DIR\n' "$RUN" "$f" \
                "$DEST_ABS/dados/$nome/${f#$alvo/}" \
                "$(meta_arquivo "$f")" "$(soma_sha "$f")" >> "$MAN"
        done
    elif [ -e "$alvo" ]; then
        publica_um "$alvo"
    else
        printf '%s\t%s\t\t\t\t\t\t\t\tNAO_ENCONTRADO\n' "$RUN" "$alvo" >> "$MAN"
        erro "não encontrado: $alvo  (atenção à CAIXA do caminho — o filesystem é case-sensitive)"
        falhas=$((falhas+1))
    fi
done

# ---------- permissões para o grupo pegar ----------
if [ -n "$GRUPO" ]; then
    if chgrp -R "$GRUPO" "$DEST_ABS" 2>/dev/null; then
        chmod -R g+rX "$DEST_ABS" 2>/dev/null
        log "permissões: grupo $GRUPO com leitura em $DEST_ABS"
    else
        erro "não consegui chgrp para $GRUPO (você é membro? o grupo existe?) — destino segue só seu"
    fi
fi

# ---------- empacotamento ----------
if [ "$FAZ_TAR" -eq 1 ]; then
    if tem tar; then
        pacote="$DEST_ABS/pacote_$(date +%Y%m%d_%H%M%S).tar.gz"
        if (cd "$DEST_ABS" && tar czf "$pacote" dados 2>/dev/null); then
            log "pacote: $pacote ($(meta_arquivo "$pacote" | cut -f1) bytes)"
            log "        sha256: $(soma_sha "$pacote")"
        else
            erro "falha ao empacotar"
        fi
    else
        erro "tar ausente — pulando --tar"
    fi
fi

# ---------- resumo + instrução de retirada ----------
log ""
log "== resumo (nó $NO)"
log "   copiados: $copiados | já publicados: $pulados | falhas: $falhas"
log "   destino:  $DEST_ABS"
log "   manifesto: $MAN (run=$RUN)"
log ""
log "== como as pessoas pegam"
log "   scp -r $(id -un)@$NO:$DEST_ABS ."
log "   (ou WinSCP/Cursor Remote-SSH apontando para $DEST_ABS)"
log "   Confira a integridade pelo MANIFESTO.tsv antes de usar."

[ "$falhas" -eq 0 ] || exit 1
