#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explora_servidor.py — navega e baixa arquivos do servidor SAS por SSH.

RODA NA SUA MÁQUINA (ou na VDI). Só lê o servidor; nunca escreve nele. Complementa
`publica_arquivos.sh` (que roda DENTRO do servidor e publica com manifesto): aqui o caso
é o inverso — você ainda não sabe o caminho e quer garimpar antes de puxar.

Primeiro uso: grave seu usuário e o servidor padrão (a senha NUNCA é gravada).

    python explora_servidor.py config --salvar-user SEU.USUARIO --salvar-host srv-sasprd04n1
    python explora_servidor.py diagnostico          # confere ssh, conexão, ferramentas, acesso

Depois, o host vira opcional e o usuário vem da config:

    python explora_servidor.py navegar /riscosbv/cobranca
    python explora_servidor.py --host outro-srv listar /riscosbv/cobranca/erocha
    python explora_servidor.py procurar /riscosbv/cobranca -n '*.sas7bdat'
    python explora_servidor.py --destino ~/puxados baixar /riscosbv/cobranca/erocha/mis.sas7bdat

No modo `navegar` você anda pelos diretórios e baixa direto do prompt:

    /riscosbv/cobranca > ls                 lista (entradas ficam numeradas)
    /riscosbv/cobranca > cd 3               entra pelo número; `cd nome`, `cd ..` e `cd /abs` também
    /riscosbv/cobranca > get 3              baixa a entrada 3 (arquivo ou pasta inteira)
    /riscosbv/cobranca > get *.sas7bdat     baixa por padrão
    /riscosbv/cobranca > destino ~/puxados  troca a pasta local de destino
    /riscosbv/cobranca > ?                  ajuda

AUTENTICAÇÃO — dois transportes, escolhidos sozinhos:

  · sem senha (padrão): usa o binário `ssh` do sistema e herda a sua autenticação —
    agent, chave, kerberos, ~/.ssh/config, jump host. Nada a instalar.
  · com senha: `--senha` pergunta no prompt (não ecoa) e conecta por paramiko, porque o
    OpenSSH não aceita senha não-interativa. Exige `pip install paramiko`; sem ele, dá
    para usar `--comando-ssh plink` (PuTTY).

A senha só entra por prompt ou pela variável de ambiente SAS_SSH_SENHA — nunca por
argumento de linha de comando, que fica visível na lista de processos e no histórico do
shell. Ela não é gravada em lugar nenhum.

DESEMPENHO: com o binário ssh em Linux/macOS a sessão abre UMA conexão e reaproveita
(ControlMaster), então cada `ls` custa milissegundos. No Windows e no plink isso não
existe e o script desliga sozinho, avisando: cada comando autentica de novo.

O download vem por `tar -c` no servidor e é extraído localmente em streaming: uma conexão
só, estrutura preservada, nada de temporário no servidor, e todo membro do tar é validado
contra path traversal antes de escrever.

Compatibilidade: o SO dos nós não foi confirmado (Linux/AIX). A listagem sonda uma vez se
o `find` é GNU (`-printf`, que traz tipo/tamanho/data) e cai para `ls -Ap1` (POSIX, só
nomes); o `tar` cai para sem compressão se não tiver `-z`. Toda degradação é AVISADA.
"""
from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import ntpath
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

# Preferências locais (usuário e host padrão). A SENHA NUNCA é gravada aqui.
CONFIG = os.path.join(os.path.expanduser("~"), ".config", "explora_servidor.json")


def le_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def grava_config(**campos) -> None:
    cfg = le_config()
    cfg.update({k: v for k, v in campos.items() if v})
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    os.chmod(CONFIG, 0o600)
    print(f"salvo em {CONFIG}: " + ", ".join(f"{k}={v}" for k, v in cfg.items()))


def resolve_alvo(user: str | None, host: str | None) -> tuple[str, str]:
    """usuário e host, nesta ordem: argumento > variável de ambiente > config salva."""
    cfg = le_config()
    u = user or os.environ.get("SAS_SSH_USER") or cfg.get("user")
    h = host or os.environ.get("SAS_SSH_HOST") or cfg.get("host")
    if not h:
        sys.exit("! informe o servidor: --host srv-sasprd04n1 (ou salve com `config --host ...`)")
    if "@" in h:                      # aceita user@host colado, mas o --user vence
        u_embutido, _, h = h.partition("@")
        u = u or u_embutido
    if not u:
        sys.exit("! informe o usuário: --user SEU.USUARIO (ou salve com `config --user ...`)")
    return u, h


def obtem_senha(pedir: bool) -> str | None:
    """Senha só por prompt ou variável de ambiente — nunca por argumento de linha de comando,
    que fica visível na lista de processos e no histórico do shell."""
    if os.environ.get("SAS_SSH_SENHA"):
        return os.environ["SAS_SSH_SENHA"]
    if pedir:
        return getpass.getpass("senha SSH (não é exibida): ")
    return None


# Raízes de produção — este script nunca escreve, mas a lista documenta o território.
RAIZES_PROD = ("/riscosbv", "/riscosbvf", "/infogrc", "/projetos", "/financas", "/seguros",
               "/regulatorio", "/ouvidoria", "/portfoliomis", "/digital", "/bancodigital",
               "/neon", "/auditoria", "/atendimento", "/miscomercial")


# Console do Windows costuma ser cp1252: '✓', '…' e '·' estouram com UnicodeEncodeError.
# Reconfigura para UTF-8 quando dá; senão troca os enfeites por ASCII.
try:                                   # nunca estourar por causa de enfeite
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, OSError):
    pass


def _encoda(ch: str) -> bool:
    try:
        ch.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Respeita a codificação do console (forçar UTF-8 num cp1252 daria mojibake, não solução).
OK, RETIC, PONTO = ("✓", "…", "·") if _encoda("✓") else ("*", "...", "-")


def humano(n: int | None) -> str:
    if n is None:
        return "?"
    for u in ("B", "K", "M", "G", "T"):
        if n < 1024 or u == "T":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024.0
    return "?"


class TransporteExec:
    """Usa o binário `ssh` do sistema: herda sua autenticação (agent, chave, kerberos,
    ~/.ssh/config, jump host). Não aceita senha — o OpenSSH não lê senha de stdin."""

    def __init__(self, alvo, comando_ssh="ssh", multiplex=None, dry_run=False):
        self.alvo, self.dry_run = alvo, dry_run
        self.base = shlex.split(comando_ssh)
        exe = os.path.basename(self.base[0]).lower().removesuffix(".exe")
        # ControlMaster não existe no OpenSSH do Windows nem no plink.
        self.multiplex = ((os.name != "nt" and exe == "ssh") if multiplex is None else multiplex)
        self.opts, self.socket, self._dir = [], None, None

    def abre(self):
        self._dir = tempfile.mkdtemp(prefix="explora_ssh_")
        if self.multiplex:
            self.socket = os.path.join(self._dir, "s")
            self.opts = ["-o", "ControlMaster=auto", "-o", f"ControlPath={self.socket}",
                         "-o", "ControlPersist=60"]
        elif os.name == "nt":
            print("  ! sem multiplexação (OpenSSH do Windows não tem ControlMaster): "
                  "cada comando autentica de novo.", file=sys.stderr)

    def fecha(self):
        if self.socket and os.path.exists(self.socket):
            subprocess.run(self.base + ["-O", "exit", "-o", f"ControlPath={self.socket}", self.alvo],
                           capture_output=True)
        if self._dir:
            try:
                os.rmdir(self._dir)
            except OSError:
                pass

    def argv(self, cmd):
        return self.base + self.opts + [self.alvo, cmd]

    def roda(self, cmd):
        if self.dry_run:
            print("  [dry-run]", " ".join(shlex.quote(a) for a in self.argv(cmd)), file=sys.stderr)
            return "", "", 0
        p = subprocess.run(self.argv(cmd), capture_output=True)
        return (p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"), p.returncode)

    def stream(self, cmd):
        """Devolve (arquivo-binário, encerra()) para ler a saída em fluxo."""
        p = subprocess.Popen(self.argv(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def encerra():
            p.stdout.close()
            err = p.stderr.read().decode("utf-8", "replace")
            p.wait()
            return p.returncode, err
        return p.stdout, encerra


class TransporteParamiko:
    """SSH em Python puro — é o caminho quando a autenticação é por SENHA (o binário ssh
    não aceita senha não-interativa). Requer `pip install paramiko`."""

    def __init__(self, user, host, senha=None, porta=22, dry_run=False, aceitar_host_novo=False):
        self.user, self.host, self.senha, self.porta = user, host, senha, porta
        self.alvo, self.dry_run, self.cli = f"{user}@{host}", dry_run, None
        self.multiplex = True          # uma sessão só, por natureza
        self.aceitar_host_novo = aceitar_host_novo

    def abre(self):
        if self.dry_run:
            return
        try:
            import paramiko  # noqa: PLC0415
        except ImportError:
            sys.exit("! autenticação por senha exige paramiko: `pip install paramiko`\n"
                     "  (alternativa sem instalar nada: --comando-ssh plink, do PuTTY)")
        self.cli = paramiko.SSHClient()
        self.cli.load_system_host_keys()
        # RejectPolicy por padrão: host key desconhecida recusa a conexão em vez de
        # aceitar com só um aviso no stderr (fácil de não ver — e é exatamente esse
        # momento que protege contra MITM numa rede interna, que é onde a senha viaja).
        # --aceitar-host-novo troca para WarningPolicy no primeiro uso com um servidor
        # ainda fora do known_hosts da VDI — risco assumido explicitamente, não default.
        if self.aceitar_host_novo:
            self.cli.set_missing_host_key_policy(paramiko.WarningPolicy())
        else:
            self.cli.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            self.cli.connect(self.host, port=self.porta, username=self.user, password=self.senha,
                             look_for_keys=not self.senha, allow_agent=not self.senha, timeout=30)
        except paramiko.AuthenticationException:
            sys.exit(f"! usuário ou senha recusados para {self.alvo}")
        except paramiko.SSHException as e:
            if "not found in known_hosts" in str(e) and not self.aceitar_host_novo:
                sys.exit(f"! host key de {self.host} não está no known_hosts — recusado por segurança.\n"
                         "  Confirme o servidor e rode de novo com --aceitar-host-novo (aceita esta "
                         "  vez com aviso), ou conecte uma vez via `ssh`/`ssh-keyscan` para gravar a "
                         "  chave no known_hosts do sistema.")
            sys.exit(f"! não consegui conectar em {self.host}:{self.porta} — {e}\n"
                     "  (rede/VPN, nome do servidor, ou porta bloqueada)")
        except OSError as e:
            sys.exit(f"! não consegui conectar em {self.host}:{self.porta} — {e}\n"
                     "  (rede/VPN, nome do servidor, ou porta bloqueada)")

    def fecha(self):
        if self.cli:
            self.cli.close()

    def roda(self, cmd):
        if self.dry_run:
            print(f"  [dry-run] paramiko {self.alvo}: {cmd}", file=sys.stderr)
            return "", "", 0
        _, out, err = self.cli.exec_command(cmd)
        saida = out.read().decode("utf-8", "replace")
        erro = err.read().decode("utf-8", "replace")
        return saida, erro, out.channel.recv_exit_status()

    def stream(self, cmd):
        _, out, err = self.cli.exec_command(cmd)

        def encerra():
            rc = out.channel.recv_exit_status()
            return rc, err.read().decode("utf-8", "replace")
        return out, encerra


class Servidor:
    """Comandos de leitura sobre um transporte (binário ssh ou paramiko)."""

    def __init__(self, transporte, dry_run: bool = False):
        self.tp = transporte
        self.host = transporte.alvo
        self.dry_run = dry_run
        self.gnu_find = None          # descoberto na sonda do primeiro `listar`
        self._tar_z = None            # o tar do servidor aceita -z?

    # -- conexão ------------------------------------------------------------
    def __enter__(self):
        self.tp.abre()
        return self

    def __exit__(self, *exc):
        self.tp.fecha()

    def executa(self, comando_remoto: str):
        """Roda um comando de LEITURA no servidor. Devolve (saida, erro, codigo)."""
        return self.tp.roda(comando_remoto)

    # -- leitura ------------------------------------------------------------
    def _tem_find_gnu(self) -> bool:
        """Sonda única e inofensiva: `-printf` só existe no find do GNU (Linux), não no AIX.
        Detectar por sonda e não pelo resultado da 1ª listagem evita concluir 'não tem GNU'
        só porque o diretório estava vazio."""
        if self.gnu_find is None:
            if self.dry_run:
                self.gnu_find = True
            else:
                _, _, rc = self.executa("find / -maxdepth 0 -printf '' 2>/dev/null")
                self.gnu_find = rc == 0
                if not self.gnu_find:
                    print("  ! `find -printf` indisponível (não-GNU): listando só nomes, "
                          "sem tamanho/data.", file=sys.stderr)
        return self.gnu_find

    def listar(self, caminho: str) -> list[dict]:
        """Entradas de um diretório: [{'tipo','nome','tamanho','data'}]. Ordena pasta antes."""
        q = shlex.quote(caminho)
        if self._tem_find_gnu():
            # find GNU traz tipo/tamanho/data numa tacada e aguenta nome com espaço
            out, err, rc = self.executa(
                f"find {q} -maxdepth 1 -mindepth 1 -printf '%y\\t%s\\t%TY-%Tm-%Td\\t%f\\n' 2>/dev/null")
            if rc != 0:
                print(f"  ! {err.strip() or 'falha ao listar'}", file=sys.stderr)
                return []
            itens = []
            for linha in out.splitlines():
                partes = linha.split("\t", 3)
                if len(partes) != 4:
                    continue
                tipo, tam, data, nome = partes
                itens.append(dict(tipo="dir" if tipo == "d" else "arq", nome=nome,
                                  tamanho=int(tam) if tam.isdigit() else None, data=data))
            return sorted(itens, key=lambda e: (e["tipo"] != "dir", e["nome"].lower()))
        out, err, rc = self.executa(f"ls -Ap1 {q}")
        if rc != 0:
            print(f"  ! {err.strip() or 'falha ao listar'}", file=sys.stderr)
            return []
        itens = [dict(tipo="dir" if n.endswith("/") else "arq", nome=n.rstrip("/"),
                      tamanho=None, data="") for n in out.splitlines() if n.strip()]
        return sorted(itens, key=lambda e: (e["tipo"] != "dir", e["nome"].lower()))

    def existe_dir(self, caminho: str) -> bool:
        _, _, rc = self.executa(f"test -d {shlex.quote(caminho)}")
        return rc == 0

    def procurar(self, raiz: str, padrao: str, limite: int = 500) -> list[str]:
        out, err, rc = self.executa(
            f"find {shlex.quote(raiz)} -name {shlex.quote(padrao)} 2>/dev/null | head -n {int(limite)}")
        if rc != 0 and not out:
            print(f"  ! {err.strip() or 'falha na busca'}", file=sys.stderr)
        return [l for l in out.splitlines() if l.strip()]

    def tamanho_de(self, caminhos: list[str]) -> int | None:
        alvos = " ".join(shlex.quote(c) for c in caminhos)
        out, _, rc = self.executa(f"du -sk {alvos} 2>/dev/null | awk '{{s+=$1}} END {{print s}}'")
        try:
            return int(out.strip()) * 1024
        except (ValueError, AttributeError):
            return None

    # -- download -----------------------------------------------------------
    def baixar(self, caminhos: list[str], destino: str, incluir: str | None = None,
               max_mb: float | None = None) -> int:
        """Puxa arquivos/pastas via `tar -c` no servidor, extraindo em streaming aqui."""
        if not caminhos:
            return 0
        pai = posixpath.dirname(caminhos[0].rstrip("/")) or "/"
        nomes = [posixpath.basename(c.rstrip("/")) for c in caminhos]
        if any((posixpath.dirname(c.rstrip("/")) or "/") != pai for c in caminhos):
            total = 0                       # caminhos de pastas diferentes: um de cada vez
            for c in caminhos:
                total += self.baixar([c], destino, incluir, max_mb)
            return total

        aprox = self.tamanho_de(caminhos)
        if aprox is not None:
            print(f"  ~{humano(aprox)} a transferir", flush=True)
        if max_mb and aprox is None:
            # Tamanho desconhecido (du falhou/sem permissão): o guard evaporava — o
            # `and aprox` deixava passar exatamente o caso em que não se sabe o
            # volume. Desconhecido é tratado como "pode estourar", não como "cabe".
            print(f"  ! não consegui medir o tamanho e --max-mb={max_mb} foi pedido — "
                  f"abortando (rode sem --max-mb para baixar assim mesmo)",
                  file=sys.stderr)
            return 0
        if max_mb and aprox and aprox > max_mb * 1024 * 1024:
            print(f"  ! acima do limite de {max_mb}MB (--max-mb) — abortando", file=sys.stderr)
            return 0

        alvos = " ".join(shlex.quote(n) for n in nomes)
        if self._tar_z is None:
            _, _, rz = self.executa("tar --help 2>&1 | grep -q -- -z")
            self._tar_z = rz == 0 or self.dry_run
        flag = "-czf" if self._tar_z else "-cf"
        cmd = f"tar {flag} - -C {shlex.quote(pai)} {alvos}"
        if self.dry_run:
            self.tp.roda(cmd)
            return 0
        os.makedirs(destino, exist_ok=True)
        fluxo, encerra = self.tp.stream(cmd)
        n = 0
        incompleto = False
        try:
            with tarfile.open(fileobj=fluxo, mode="r|gz" if self._tar_z else "r|") as tf:
                for m in tf:
                    if not self._membro_seguro(m):
                        print(f"  ! ignorado (caminho suspeito): {m.name}", file=sys.stderr)
                        continue
                    if m.isfile() and incluir and not fnmatch.fnmatch(posixpath.basename(m.name), incluir):
                        continue
                    # filter="data": rejeita links/permissões perigosos além do
                    # nosso guard. Disponível a partir do Python 3.12.
                    try:
                        tf.extract(m, destino, filter="data")
                    except TypeError:
                        tf.extract(m, destino)
                    if m.isfile():
                        n += 1
                        print(f"  {OK} {m.name} ({humano(m.size)})")
        except tarfile.TarError as e:
            # Transferência truncada/corrompida. Antes só imprimia esta linha (fácil de
            # perder entre os "OK" de cada arquivo) e devolvia a contagem PARCIAL, que o
            # chamador exibia como "N arquivo(s) em ...", idêntico a um download
            # completo. Marca como incompleta para o aviso final aparecer.
            print(f"  ! erro lendo o tar remoto: {e}", file=sys.stderr)
            incompleto = True
        finally:
            rc, err = encerra()
        if rc != 0 and err.strip():
            print(f"  ! servidor: {err.strip()}", file=sys.stderr)
            incompleto = True
        if incompleto:
            print(f"  !! TRANSFERÊNCIA INCOMPLETA: {n} arquivo(s) extraído(s) antes da "
                  f"falha — NÃO trate este destino como cópia completa.", file=sys.stderr)
        return n

    @staticmethod
    def _membro_seguro(m: tarfile.TarInfo) -> bool:
        """Barra path traversal: nada de caminho absoluto, '..' ou link para fora."""
        nome = m.name.replace("\\", "/")
        if nome.startswith("/") or ".." in nome.split("/"):
            return False
        # Absoluto no estilo Windows. A normalização de "\\" para "/" acima faz um
        # membro "C:\\evil" virar "C:/evil", que não começa com "/" e passava — e no
        # Windows os.path.join(destino, "C:/evil") DESCARTA destino, escrevendo fora
        # da pasta de download.
        if ntpath.isabs(nome) or re.match(r"^[A-Za-z]:", nome):
            return False
        if (m.issym() or m.islnk()) and (m.linkname.startswith("/") or ".." in m.linkname.split("/")):
            return False
        return True


# ---------------------------------------------------------------- modo navegar
AJUDA = """
  ls [padrão]      lista o diretório atual (as entradas ficam numeradas)
  cd <n|nome|..>   entra na pasta (por número, nome ou caminho absoluto)
  get <n|padrão|.> baixa: número da entrada, glob (*.sas7bdat) ou '.' para a pasta toda
  procurar <glob>  busca recursiva a partir daqui
  destino [dir]    mostra ou troca a pasta local de destino
  pwd | ? | q
"""


def navegar(srv: Servidor, inicio: str, destino: str) -> int:
    atual = inicio if srv.existe_dir(inicio) or srv.dry_run else "/"
    if atual != inicio:
        print(f"! {inicio} não é um diretório acessível; começando em /", file=sys.stderr)
    itens: list[dict] = []

    def mostra(padrao: str | None = None):
        nonlocal itens
        itens = srv.listar(atual)
        vis = [e for e in itens if not padrao or fnmatch.fnmatch(e["nome"], padrao)]
        if not vis:
            print("  (vazio)")
            return
        for i, e in enumerate(vis, 1):
            marca = "/" if e["tipo"] == "dir" else " "
            print(f"  [{i:>3}] {'dir ' if e['tipo'] == 'dir' else humano(e['tamanho']):>7} "
                  f"{e['data']:<10} {e['nome']}{marca}")
        itens = vis
        print(f"  — {len(vis)} entradas em {atual}")

    def resolve(arg: str) -> list[str]:
        """Argumento de get: número, glob ou '.' → lista de caminhos remotos."""
        if arg == ".":
            return [atual]
        if arg.isdigit():
            i = int(arg)
            if 1 <= i <= len(itens):
                return [posixpath.join(atual, itens[i - 1]["nome"])]
            print("  ! número fora da lista (rode `ls` antes)")
            return []
        alvo = [e for e in srv.listar(atual) if fnmatch.fnmatch(e["nome"], arg)]
        if not alvo:
            print(f"  ! nada casa com {arg}")
        return [posixpath.join(atual, e["nome"]) for e in alvo]

    def prompt() -> str:
        """Caminho encurtado: prompt com 3 níveis basta para se localizar."""
        partes = atual.strip("/").split("/")
        return (RETIC + "/" if len(partes) > 3 else "/") + "/".join(partes[-3:])

    print(f"conectado a {srv.host} {PONTO} destino local: {destino}")
    mostra()
    while True:
        try:
            linha = input(f"\n{prompt()} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not linha:
            continue
        cmd, _, arg = linha.partition(" ")
        arg = arg.strip()
        if cmd in ("q", "sair", "exit"):
            return 0
        if cmd in ("?", "ajuda", "help"):
            print(AJUDA)
        elif cmd == "ls":
            mostra(arg or None)
        elif cmd == "pwd":
            print(" ", atual)
        elif cmd == "cd":
            if arg == "..":
                novo = posixpath.dirname(atual.rstrip("/")) or "/"
            elif arg.isdigit() and 1 <= int(arg) <= len(itens):
                novo = posixpath.join(atual, itens[int(arg) - 1]["nome"])
            elif arg.startswith("/"):
                novo = arg
            else:
                novo = posixpath.join(atual, arg)
            if srv.existe_dir(novo):
                atual = posixpath.normpath(novo)
                mostra()
            else:
                print(f"  ! não é diretório: {novo}")
        elif cmd == "procurar":
            achados = srv.procurar(atual, arg or "*")
            for a in achados:
                print("  ", a)
            print(f"  — {len(achados)} resultado(s)")
        elif cmd == "destino":
            if arg:
                destino = os.path.abspath(os.path.expanduser(arg))
            print("  destino local:", destino)
        elif cmd == "get":
            caminhos = resolve(arg or ".")
            if caminhos:
                n = srv.baixar(caminhos, destino)
                print(f"  {n} arquivo(s) em {destino}")
        else:
            print("  ! comando desconhecido — `?` para a ajuda")


def diagnostico(srv: Servidor, caminho: str) -> int:
    """Confere, em ordem, tudo de que o script depende — para o erro vir nomeado."""
    import platform
    print(f"python      : {platform.python_version()} em {platform.system()} {platform.release()}")
    if isinstance(srv.tp, TransporteExec):
        exe = srv.tp.base[0]
        print(f"transporte  : binario ssh ({exe} -> {shutil.which(exe) or 'NAO ENCONTRADO no PATH'})")
        print(f"multiplex   : {'sim' if srv.tp.multiplex else 'nao (Windows/plink: normal)'}")
        if not shutil.which(exe):
            print("\n  ! sem cliente ssh. No Windows: Configuracoes > Aplicativos > Recursos "
                  "opcionais > Cliente OpenSSH. Ou use --comando-ssh plink, ou --senha (paramiko).")
            return 1
    else:
        try:
            import paramiko
            print(f"transporte  : paramiko {paramiko.__version__} (autenticacao por senha)")
        except ImportError:
            print("transporte  : paramiko AUSENTE -> `pip install paramiko`")
            return 1
    print(f"alvo        : {srv.host}")
    out, err, rc = srv.executa("echo ok")
    print(f"conexao     : {'ok' if out.strip() == 'ok' else 'FALHOU'}")
    if rc != 0:
        print("  !", err.strip()[:300] or "sem detalhe")
        return 1
    for nome, cmd in (("find GNU", "find / -maxdepth 0 -printf '' 2>/dev/null"),
                      ("tar", "command -v tar >/dev/null"),
                      ("gzip no tar", "tar --help 2>&1 | grep -q -- -z"),
                      ("du", "command -v du >/dev/null")):
        _, _, r = srv.executa(cmd)
        print(f"{nome:<12}: {'ok' if r == 0 else 'ausente/diferente — ver observacao abaixo'}")
    _, _, r = srv.executa(f"test -d {shlex.quote(caminho)}")
    print(f"{'acesso':<12}: {'ok' if r == 0 else 'SEM ACESSO'} a {caminho}")
    print("\nobservacoes: sem `find` GNU a listagem perde tamanho/data (segue funcionando);\n"
          "sem `-z` no tar o download cai para tar sem compressao (mais lento, funciona);\n"
          "sem `du` o script so nao consegue avisar o tamanho antes de baixar.")
    return 0


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="servidor (ex.: srv-sasprd04n1). Aceita usuario@servidor.")
    ap.add_argument("--user", help="seu usuário no servidor (default: o salvo em config)")
    ap.add_argument("--senha", action="store_true",
                    help="autenticar por senha (pergunta no prompt; usa paramiko)")
    ap.add_argument("--aceitar-host-novo", action="store_true",
                    help="com --senha: aceita host key ainda fora do known_hosts (avisa em vez "
                         "de recusar). Sem isto a conexão por senha recusa host desconhecido.")
    ap.add_argument("--porta", type=int, default=22)
    ap.add_argument("--destino", default="./puxados", help="pasta local de destino (default: ./puxados)")
    ap.add_argument("--comando-ssh", default="ssh", help="binário de ssh (default: ssh)")
    ap.add_argument("--dry-run", action="store_true", help="só imprime os comandos, não executa")
    ap.add_argument("--sem-multiplex", action="store_true",
                    help="não usar ControlMaster (automático no Windows/plink)")
    sub = ap.add_subparsers(dest="acao", required=True)

    p = sub.add_parser("config", help="salva usuário/servidor padrão (nunca a senha)")
    p.add_argument("--salvar-user", dest="salvar_user")
    p.add_argument("--salvar-host", dest="salvar_host")

    p = sub.add_parser("navegar", help="modo interativo: anda pelas pastas e baixa")
    p.add_argument("caminho", nargs="?", default="/riscosbv/cobranca")

    p = sub.add_parser("listar", help="lista um diretório e sai")
    p.add_argument("caminho")

    p = sub.add_parser("procurar", help="busca recursiva por padrão de nome")
    p.add_argument("raiz")
    p.add_argument("-n", "--nome", required=True, help="glob, ex.: '*.sas7bdat'")

    p = sub.add_parser("diagnostico", help="confere ssh, conexão, ferramentas e acesso")
    p.add_argument("caminho", nargs="?", default="/riscosbv/cobranca")

    p = sub.add_parser("baixar", help="baixa arquivos/pastas")
    p.add_argument("caminho", nargs="+")
    p.add_argument("--incluir", help="filtra por glob dentro da pasta, ex.: '*.csv'")
    p.add_argument("--max-mb", type=float, help="aborta se o total passar disso")

    a = ap.parse_args()
    if a.acao == "config":
        grava_config(user=a.salvar_user, host=a.salvar_host)
        return 0
    destino = os.path.abspath(os.path.expanduser(a.destino))

    user, host = resolve_alvo(a.user, a.host)
    senha = obtem_senha(a.senha)
    if senha:
        tp = TransporteParamiko(user, host, senha, a.porta, a.dry_run, a.aceitar_host_novo)
    else:
        mux = False if a.sem_multiplex else None
        tp = TransporteExec(f"{user}@{host}", a.comando_ssh, mux, a.dry_run)
    with Servidor(tp, a.dry_run) as srv:
        if a.acao == "diagnostico":
            return diagnostico(srv, a.caminho)
        if a.acao == "navegar":
            return navegar(srv, a.caminho, destino)
        if a.acao == "listar":
            for e in srv.listar(a.caminho):
                marca = "/" if e["tipo"] == "dir" else ""
                print(f"{'dir' if e['tipo'] == 'dir' else humano(e['tamanho']):>8}  "
                      f"{e['data']:<10}  {e['nome']}{marca}")
            return 0
        if a.acao == "procurar":
            for c in srv.procurar(a.raiz, a.nome):
                print(c)
            return 0
        if a.acao == "baixar":
            n = srv.baixar(a.caminho, destino, a.incluir, a.max_mb)
            print(f"{n} arquivo(s) em {destino}")
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
