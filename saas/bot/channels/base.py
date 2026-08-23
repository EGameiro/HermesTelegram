"""Contrato comum dos canais + registro de senders + contexto de mensagem.

O núcleo (engine) NÃO sabe se está falando com Telegram ou WhatsApp: ele recebe um
`Inbound` já normalizado e um `Sender` (transporte do canal), e responde por um
`MsgContext`. O agendador usa o registro `sender_for(canal)` para entregar lembretes
no canal em que cada tenant está conectado.

Identidade por canal:
- telegram: `identificador` = TelegramUserId (como string)
- whatsapp: `identificador` = telefone só dígitos (E.164 sem '+')
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Inbound:
    """Mensagem recebida, já normalizada pelo adaptador de canal."""
    canal: str
    identificador: str            # identidade autenticada do remetente no canal
    nome: str | None = None       # username / pushname (exibição)
    text: str = ""                # texto (vazio se veio só áudio; o engine transcreve)
    voice_ref: object | None = None  # referência opaca p/ o sender baixar o áudio
    voice_seg: int = 0            # duração do áudio recebido (s), se o canal informar


class Sender(ABC):
    """Transporte de saída de um canal. Uma instância por canal, registrada no boot."""
    canal: str = ""

    @abstractmethod
    def send_text(self, identificador, text):
        ...

    def send_typing(self, identificador):
        """Indicador de 'digitando' (opcional — nem todo canal suporta)."""
        return None

    @abstractmethod
    def send_voice(self, identificador, audio_bytes, caption=None) -> bool:
        """Envia áudio; retorna True se enviou. False -> o chamador cai p/ texto."""
        ...

    def baixar_audio(self, voice_ref) -> tuple[bytes, str, str] | None:
        """Baixa o áudio recebido. Retorna (bytes, filename, mime) ou None.
        Default: canal não suporta voz recebida."""
        return None


class MsgContext:
    """Fachada de resposta ligada a (sender, identificador) de UMA mensagem."""

    def __init__(self, sender: Sender, identificador: str, tenant: dict | None = None):
        self.sender = sender
        self.identificador = identificador
        self.tenant = tenant

    @property
    def canal(self):
        return self.sender.canal

    def reply(self, text):
        self.sender.send_text(self.identificador, text)

    def typing(self):
        self.sender.send_typing(self.identificador)

    def voz(self, audio_bytes, caption=None) -> bool:
        return self.sender.send_voice(self.identificador, audio_bytes, caption)


# --- Registro de senders (usado pelo agendador p/ entregar em qualquer canal) ---
_SENDERS: dict[str, Sender] = {}


def register(sender: Sender):
    _SENDERS[sender.canal] = sender


def sender_for(canal: str) -> Sender | None:
    return _SENDERS.get(canal)


def canais_registrados() -> list[str]:
    return list(_SENDERS.keys())
