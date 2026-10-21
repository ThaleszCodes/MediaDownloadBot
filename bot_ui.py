"""Portuguese chat presentation. HTML is escaped at every user-input boundary."""
from datetime import datetime, timezone, timedelta
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup


SUPPORT_URL = 'https://t.me/Tz_Kys'
NOTICE = ('⚠️ <b>Importante:</b> talvez nem todas as mídias do álbum sejam baixadas ou enviadas. '
          'O uso é por sua conta e risco; não nos responsabilizamos por mídias ausentes ou falhas de download e envio.')


def support_button():
    return Button('💬 Suporte humano', url=SUPPORT_URL)


def menu():
    return InlineKeyboardMarkup([
        [Button('📥 Baixar mídias', callback_data='menu:download')],
        [Button('👤 Minha conta', callback_data='menu:account'), Button('💎 Planos', callback_data='menu:plans')],
        [Button('❓ Como funciona', callback_data='menu:help')],
        [support_button()],
    ])


def back():
    return InlineKeyboardMarkup([[support_button()], [Button('🏠 Menu inicial', callback_data='menu:home')]])


def again():
    return InlineKeyboardMarkup([
        [Button('📥 Baixar outro álbum', callback_data='menu:download')],
        [Button('👤 Minha conta', callback_data='menu:account'), Button('🏠 Início', callback_data='menu:home')],
        [support_button()],
    ])


def account_text(state):
    identity = f"👤 <b>Conta Telegram:</b> <code>{state.get('telegram_id', '—')}</code>\n"
    delivered = f"📦 <b>Total enviado:</b> {state.get('total_delivered', 0)} mídia(s)\n"
    if state['premium']:
        try:
            date = datetime.fromisoformat(state['expires_at'].replace('Z', '+00:00'))
            try:
                local_zone = ZoneInfo('America/Sao_Paulo')
            except ZoneInfoNotFoundError:
                # Some Termux installations do not include the IANA timezone database.
                local_zone = timezone(timedelta(hours=-3), name='Brasília')
            expiry = date.astimezone(local_zone).strftime('%d/%m/%Y às %Hh%M')
        except (ValueError, TypeError, AttributeError):
            expiry = 'Consulte novamente em instantes'
        return ('💎 <b>Seu Premium está ativo!</b>\n\n' + identity +
                f"🗓 <b>Plano:</b> {escape(state.get('plan_name') or 'Premium')}\n" +
                f'📅 <b>Válido até:</b> {expiry}\n<i>Horário de Brasília</i>\n\n' +
                '♾️ <b>Downloads ilimitados enquanto o plano estiver ativo.</b>\n'
                '📦 Até 50 mídias por pedido e 49 MiB por mídia.\n\n' + delivered)
    remaining = state['trial_remaining']
    reserved = state.get('trial_reserved', 0)
    detail = f"🎁 <b>Grátis disponíveis:</b> {remaining} de 5\n✅ <b>Grátis utilizados:</b> {state.get('trial_used', 5-remaining)}\n"
    if reserved:
        detail += f'⏳ <b>Reservados em pedidos:</b> {reserved}\n'
    return ('👤 <b>Minha conta</b>\n\n' + identity + '💎 <b>Assinatura:</b> sem Premium ativo\n\n' +
            detail + delivered + '\n🔄 Se acabou de pagar, consulte novamente após a confirmação da Cakto.')


def welcome(name, state):
    greeting = escape(name or 'visitante')
    if state is None:
        badge = '⏳ Sua conta está indisponível no momento. Tente <b>Minha conta</b> em instantes.'
    elif state['premium']:
        badge = '💎 <b>Premium ativo</b> — downloads ilimitados!\n📦 Até 50 mídias por pedido e 49 MiB por mídia.'
    else:
        badge = f"🎁 Você tem <b>{state['trial_remaining']} mídias grátis</b> disponíveis."
    return (f'👋 <b>Bem-vindo, {greeting}!</b>\n'
            '<b>MediaDownloadBot</b>\n\n'
            'Suas fotos e vídeos, direto na conversa. 📥\n\n'
            '🔗 <b>Envie o link do álbum</b> e escolha o que quer receber.\n\n'
            f'{badge}\n\n' + NOTICE)


DOWNLOAD = ('📥 <b>Vamos baixar seu álbum?</b>\n\n'
            'Cole o link aqui na conversa, sem escrever nada junto:\n\n'
            '<code>https://www.erome.com/a/IDDOALBUM</code>\n\n'
            'Depois, escolha <b>fotos</b>, <b>vídeos</b> ou <b>todos</b>.\n'
            '<i>Troque IDDOALBUM pelo código do álbum que você quer baixar.</i>')
HELP = ('❓ <b>É simples usar</b>\n\n'
        '1️⃣ Envie o link público de um álbum.\n'
        '2️⃣ Escolha fotos, vídeos ou todas as mídias.\n'
        '3️⃣ Receba os arquivos aqui no chat.\n\n'
        '♾️ <b>Assinantes:</b> downloads ilimitados durante a vigência do plano.\n'
        '🎁 <b>Teste grátis:</b> 5 mídias por conta, uma única vez. Falhas confirmadas não consomem o teste.\n\n'
        '📦 <b>Por pedido:</b> até 50 mídias, 49 MiB por mídia e 10 minutos de processamento.\n'
        '⏱ Um pedido por vez; intervalo de 30 segundos entre pedidos.\n'
        '📱 Um formato incompatível pode chegar como arquivo.\n\n' + NOTICE)
# Kept as a fallback for integrations importing the old constant.
PLANS = '💎 Consulte /planos para ver as ofertas disponíveis.'


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


def money(cents):
    return f"R${cents // 100},{cents % 100:02d}"


def plans_text(offers):
    lines = ['💎 <b>Planos Premium</b>', '']
    for offer in offers:
        period = 'por semana' if offer['period_days'] == 7 else 'por mês'
        availability = '' if offer['sales_enabled'] else ' · indisponível no momento'
        lines.append(f"🗓 <b>{escape(offer['name'])}</b> — {money(offer['price_cents'])} {period}{availability}")
    lines += ['', '♾️ Downloads ilimitados enquanto o plano estiver ativo.',
              '📥 Fotos e vídeos direto na conversa.',
              '📦 Até 50 mídias por pedido e 49 MiB por arquivo.',
              '⏱ Um pedido por vez; intervalo de 30 segundos entre pedidos.',
              '', 'A compra é concluída no site externo. Confira as condições de renovação no checkout.',
              'O acesso é liberado após a confirmação do pagamento.', '', NOTICE]
    return '\n'.join(lines)


def plans_keyboard(offers):
    rows = [[Button(f"💎 Assinar {o['name']} · {money(o['price_cents'])}", callback_data='subscribe:'+o['code'])]
            for o in offers if o['sales_enabled']]
    rows += [[support_button()], [Button('🔄 Verificar meu acesso',callback_data='menu:account')],
             [Button('🏠 Menu inicial',callback_data='menu:home')]]
    return InlineKeyboardMarkup(rows)
