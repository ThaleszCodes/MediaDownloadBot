"""Portuguese chat presentation. HTML is escaped at every user-input boundary."""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup


def menu():
    return InlineKeyboardMarkup([
        [Button('📥 Baixar mídias', callback_data='menu:download')],
        [Button('👤 Minha conta', callback_data='menu:account'), Button('💎 Planos', callback_data='menu:plans')],
        [Button('❓ Como funciona', callback_data='menu:help')],
    ])


def back():
    return InlineKeyboardMarkup([[Button('🏠 Menu inicial', callback_data='menu:home')]])


def again():
    return InlineKeyboardMarkup([
        [Button('📥 Baixar outro álbum', callback_data='menu:download')],
        [Button('👤 Meu saldo', callback_data='menu:account'), Button('🏠 Início', callback_data='menu:home')],
    ])


def account_text(state):
    if state['premium']:
        try:
            date = datetime.fromisoformat(state['expires_at'].replace('Z', '+00:00'))
            expiry = date.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %Hh%M')
        except (ValueError, TypeError, AttributeError):
            expiry = 'Consulte novamente em instantes'
        return ('💎 <b>Seu Premium está ativo!</b>\n\n'
                f'📅 <b>Válido até:</b> {expiry}\n'
                '<i>Horário de Brasília</i>\n\nEnvie um álbum para começar. 📥')
    remaining = state['trial_remaining']
    if not remaining:
        return ('🎁 <b>Você usou seu teste grátis</b>\n\n'
                'Seu saldo gratuito chegou a <b>0 de 5 mídias</b>.\n'
                'Confira a seção <b>Planos</b> para acompanhar a disponibilidade do Premium.')
    return (f'🎁 <b>Seu teste grátis</b>\n\n'
            f'📸 <b>{remaining} de 5 mídias disponíveis</b>\n\n'
            'Cada foto ou vídeo enviado com sucesso usa 1 mídia do teste.\n'
            'O teste é único por conta do Telegram e não reinicia ao usar /start.')


def welcome(name, state):
    greeting = escape(name or 'visitante')
    if state is None:
        badge = '⏳ Seu saldo está indisponível no momento. Tente <b>Minha conta</b> em instantes.'
    elif state['premium']:
        badge = '💎 <b>Premium ativo</b> — pode enviar seu álbum!'
    else:
        badge = f"🎁 Você tem <b>{state['trial_remaining']} mídias grátis</b> disponíveis."
    return (f'👋 <b>Bem-vindo, {greeting}!</b>\n'
            '<b>MediaDownloadBot</b>\n\n'
            'Suas fotos e vídeos, direto na conversa. 📥\n\n'
            '🔗 <b>Envie o link do álbum</b> e escolha o que quer receber.\n\n'
            f'{badge}\n\n'
            '<i>Use somente mídias não explícitas, públicas e autorizadas.</i>')


DOWNLOAD = ('📥 <b>Vamos baixar seu álbum?</b>\n\n'
            'Cole o link aqui na conversa, sem escrever nada junto:\n\n'
            '<code>https://www.erome.com/a/IDDOALBUM</code>\n\n'
            'Depois, escolha <b>fotos</b>, <b>vídeos</b> ou <b>todos</b>.\n'
            '<i>Troque IDDOALBUM pelo código do álbum que você quer baixar.</i>')
HELP = ('❓ <b>É simples usar</b>\n\n'
        '1️⃣ Envie o link público de um álbum.\n'
        '2️⃣ Escolha fotos, vídeos ou todas as mídias.\n'
        '3️⃣ Receba os arquivos aqui no chat.\n\n'
        '🎁 <b>Teste grátis:</b> 5 mídias por conta, uma única vez. Se o álbum for maior '
        'que seu saldo, envio só o que ele permitir. Falhas confirmadas não descontam.\n\n'
        '📦 <b>Por pedido:</b> até 50 mídias, 49 MiB por arquivo e 10 minutos de processamento.\n'
        '📱 Um formato incompatível pode chegar como arquivo.\n\n'
        '⏳ Se um envio for interrompido, o saldo reservado pode precisar de revisão '
        'para evitar cobrança duplicada.\n\n'
        '🔒 Apenas conteúdo não explícito e autorizado. O bot não faz classificação visual automática.')
PLANS = ('💎 <b>Premium — em breve</b>\n\n'
         '🗓 <b>Semanal</b> · R$5,00 por semana\n'
         '📅 <b>Mensal</b> · R$15,90 por mês\n\n'
         'A contratação ainda não está disponível aqui. Estamos concluindo '
         'a ativação e a vinculação dos pagamentos.\n\n'
         '🎁 Enquanto isso, você pode usar suas 5 mídias gratuitas e acompanhar o saldo em <b>Minha conta</b>.')


def progress(sent, failed, total):
    detail = f'\n⚠️ Não enviadas: <b>{failed}</b>' if failed else ''
    return (f'📤 <b>Enviando seu álbum…</b>\n\n'
            f'✅ Enviadas: <b>{sent}/{total}</b>{detail}\n\n'
            '<i>Seus arquivos aparecem aqui na conversa. Pode aguardar. ✨</i>')


def complete(sent, failed):
    if not sent:
        return ('⚠️ <b>Não consegui enviar as mídias</b>\n\n'
                'Os arquivos podem estar indisponíveis, acima do limite ou em formato incompatível.\n'
                'Tente outro álbum público.')
    text = f'✅ <b>Prontinho!</b>\n\n📦 <b>{sent} mídia(s) enviada(s)</b> na conversa.'
    if failed:
        text += (f'\n⚠️ <b>{failed} mídia(s) não enviada(s)</b>: podem estar indisponíveis, '
                 'acima do limite ou em formato incompatível.')
    return text + '\n\nQuer baixar mais? Envie outro link. 🔗'
