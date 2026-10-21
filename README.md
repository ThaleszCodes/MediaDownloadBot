# MediaDownloadBot — Termux

Envie um link público `https://www.erome.com/a/IDDOALBUM` no privado do bot.
Ele mostra **Baixar fotos**, **Baixar vídeos** e **Baixar Todos** e envia cada mídia no chat.
Qualquer pessoa pode iniciar. O saldo grátis e os vencimentos agora ficam no Supabase.
Não precisa de IA ou FFmpeg.
Use somente conteúdo não explícito e autorizado. Não há classificação visual automática:
o bot não garante bloquear conteúdo explícito. Não contorna login ou bloqueios.

## Instalar

No Termux, execute:

```bash
pkg update && pkg upgrade -y
pkg install python git nano -y
git clone https://github.com/ThaleszCodes/MediaDownloadBot.git
cd MediaDownloadBot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Crie um bot com `/newbot` no @BotFather. Cole seu token depois do `=` no `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=COLE_SEU_TOKEN_AQUI
```

No nano: Ctrl+O, Enter e Ctrl+X. Não compartilhe o token. `.env` é ignorado pelo Git.

```bash
termux-wake-lock
python bot.py
```

Abra o bot no Telegram, envie `/start` e depois um link real de um álbum não explícito
autorizado. `IDDOALBUM` é apenas um exemplo. Ctrl+C encerra; depois use `termux-wake-unlock`.

Para iniciar de novo:

```bash
cd ~/MediaDownloadBot
source .venv/bin/activate
python bot.py
```

Desative a otimização de bateria do Termux no Android. O wake lock não garante que o
Android mantenha o processo vivo. Celular desligado, processo parado ou sem internet = bot offline.
Apenas uma instância por token. Downloads e envios de todos os usuários usam sua conexão.

## Limites e comportamento

- Até 50 mídias por álbum e 49 MiB por arquivo. Sem compressão: arquivos grandes contam como falha.
- Dois pedidos simultâneos, até três downloads de mídia simultâneos no total, um pedido por pessoa e intervalo de 30 segundos.
- Dez minutos por pedido após sair da fila. Temporários apagados ao terminar ou falhar.
- Envia fotos/vídeos na ordem do álbum, em grupos de até 10 mídias (até 64 MiB por lote).
  O próximo download ocorre durante o envio; não há pausa fixa entre arquivos. Um lote
  com apenas uma mídia é enviado individualmente. Se Telegram recusar o formato,
  tenta documento. Não promete reproduzir todo codec de vídeo no aplicativo.
- Uma falha não impede os demais arquivos. Não repete automaticamente envios com timeout,
  pois podem ter chegado mesmo sem confirmação.
- Fila e botões em andamento não persistem após reiniciar. Atualizações antigas são descartadas.
- Só aceita HTTPS e mídia nos domínios do Erome. Mudança de CDN, HTML, redirecionamentos
  ou bloqueios pode exigir ajuste. Não há bypass de proteção.
- Não grava links em logs. Mensagens enviadas permanecem no Telegram.

## Validação

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Testes com HTML sintético, HTTP simulado e Telegram simulado, sem álbuns reais.
Não foi feito envio real no Telegram, pois o token deve ser configurado no seu celular.
Teste manualmente: /start, link inválido, três botões num álbum não explícito autorizado,
álbum inexistente e segundo pedido durante download. O parser depende do HTML público atual.

## Atualizar no Termux

Pare o bot com Ctrl+C e execute:

```bash
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

O pipeline mantém até três arquivos adiantados por pedido e até três downloads ativos
no total. Lotes são limitados a 64 MiB de mídia para conter memória, além do overhead
do Python e HTTP. Reserve espaço temporário no celular (até cerca de 300 MiB por pedido).
O Telegram pode solicitar uma pausa com RetryAfter: o bot respeita esse tempo.
A melhoria reduz esperas entre arquivos, mas não aumenta a velocidade da sua conexão.

## Controle de acesso

- Cada ID do Telegram recebe 5 mídias grátis uma vez. `/conta` consulta saldo e vencimento.
- Antes de baixar, o backend reserva até o saldo disponível e corta o álbum nesse limite.
- Envios confirmados são contabilizados por lote, com idempotência no banco. Falhas
  definitivas liberam saldo quando o pedido termina; timeout, cancelamento ou crash
  mantêm a reserva para revisão, pois o Telegram pode ter recebido a mídia.
- Reservas abandonadas exigem reconciliação de suporte em `bot_download_jobs`.
- Tabelas têm RLS e acesso negado a anon/authenticated. Só backend privilegiado acessa.
- Backend usa `SUPABASE_URL` e `BOT_ACCESS_SECRET` (apenas Railway ou .env local).
- A Edge Function autentica esse segredo por SHA-256; o código contém só o hash.
  Para rotação, atualize o segredo do bot e `BOT_ACCESS_SECRET_SHA256` nos secrets da função.
- `supabase/schema.sql` é snapshot inicial para um banco vazio, não deve ser reaplicado.
- Os checkouts semanal e mensal estão em `bot_plans`, com disponibilidade consultada em tempo real.
- O receptor Cakto e a lógica de pagamento estão em `supabase/webhook.sql` e
  `supabase/functions/cakto-webhook`. Cadastro na Cakto e segredo são necessários.
  O checkout dentro do Telegram continua desativado; a regra de Stars precisa ser resolvida.
- Assinaturas só são aceitas se existir concessão válida em `bot_subscriptions`;
  nenhuma mensagem ou link do comprador pode liberar Premium.
- Não iniciar vendas antes de validar cobrança, reembolso, vínculo de conta e limites pagos.

## Webhook Cakto

URL de produção:
`https://afdelhhqpdgdvsiklogi.supabase.co/functions/v1/cakto-webhook`

Na Cakto, crie um webhook **apenas para o produto MediaDownloadBot** com os eventos:
`purchase_approved`, `subscription_renewed`, `subscription_late_recovered`, `refund`,
`chargeback`, `subscription_canceled`, `subscription_paused`, `subscription_resumed`,
`subscription_late`, `subscription_renewal_refused`, `refund_requested`.

Copie o segredo GERADO PELA CAKTO para Supabase > Edge Functions > Secrets,
nome `CAKTO_WEBHOOK_SECRET`. Não use o token do bot, não publique o segredo.
Sem esse secret o endpoint responde 503 e nunca libera acesso.
HMAC-SHA256 com timestamp de até 5 minutos é validado sobre o corpo original.
Entregas antigas sem header de assinatura aceitam o `secret` no corpo conforme a documentação.
Um header inválido nunca pode cair na validação alternativa.

### Associação da compra

O backend externo autenticado usa `bot_create_checkout(telegram_id, plan_code)`
para gerar uma sessão aleatória de 24h. O link contém `?callback=TOKEN`.
O ID do Telegram deve vir de uma autenticação verificada, nunca de campo digitado
num formulário público. Este RPC não é público nem acessível pelo frontend.
Não há endpoint público de geração de sessões ou novo botão de checkout no bot.
`bot_plans.sales_enabled` controla a disponibilidade de cada plano; foi habilitado para o teste solicitado.

O webhook associa a compra pelo callback; renovações podem usar a assinatura
já vinculada. Um callback não pode vincular duas compras iniciais diferentes.
Compras pelos links crus, sem sessão, ficam `pending_identity` para suporte;
um e-mail ou número do pedido enviado no chat nunca libera acesso automaticamente.
Configure `provider_offer_id` e `provider_product_id` em bot_plans quando os IDs
forem consultados na conta Cakto. Até lá, o webhook assinado aceita apenas os
checkouts exatos cadastrados, moeda BRL e preço integral configurado. Cupons exigem
uma política explícita antes de ativar. Eventos de teste da Cakto usam oferta fixa
e serão ignorados pelo filtro; não use dados de teste para habilitar Premium real.

- A aprovação cria um período por ID de pedido, sem duplicar por retry ou evento de renovação.
- Reembolso/chargeback revogam aquele pagamento; aprovação tardia não o reativa.
- Cancelamento e atraso são registrados e preservam períodos já pagos.
- Mensal usa mês de calendário; semanal usa 7 dias; novas cobranças acumulam a partir do fim do acesso.
- V1 (objeto) e V2 (array) são aceitos, com limite de 20 pedidos por entrega.
- Campos pessoais e o secret nunca são persistidos no histórico.
- Falha de banco responde 503. A Cakto **não retenta automaticamente respostas HTTP
  de erro**; monitore o histórico e reenvie manualmente após corrigir. A idempotência
  permite repetir eventos com segurança. `pending_identity` também exige revisão e replay.

Testes adicionais:

```bash
node --experimental-strip-types --test tests/webhook.test.mjs
```

`tests/webhook.sql` testa a concessão real no banco com fixtures e rollback,
incluindo replay, renovação, cancelamento, chargeback fora de ordem, valores inválidos,
identidade pendente e mês de calendário. Não cria cobranças reais.

## Menu do Telegram

O bot usa mensagens HTML e botões inline para baixar, consultar a conta, ver planos
(em breve) e abrir ajuda. `/start`, `/conta`, `/planos` e `/help` ficam no menu de
comandos. Nomes de usuários são escapados antes da formatação. Datas de vencimento
são mostradas no fuso de Brasília. Esta atualização visual não ativa vendas.

## Minha conta e assinatura externa

`supabase/account.sql` acrescenta consultas privadas com saldo usado, disponível,
reservado, total enviado, plano e vencimento. Os botões da tela de planos são
gerados a partir do banco, respeitando `sales_enabled`.

O botão Assinar solicita uma sessão individual ao backend e fornece um link
para `subscription-checkout`. Esse endpoint valida a sessão e redireciona ao
site externo da Cakto com `callback` opaco, sem confiar em ID de usuário digitado.
O botão Verificar pagamento consulta novamente o banco; nunca concede acesso por si só.
Não há coleta de cartão, Pix ou confirmação de pagamento no Telegram. Isso não
constitui uma garantia de conformidade: as regras do Telegram exigem Stars para
vendas digitais dentro do app, inclusive quando há portais externos.

As funções de acesso e redirecionamento já estão publicadas no Supabase. O Termux
precisa da main atual e de SUPABASE_URL e BOT_ACCESS_SECRET válidos no .env.
Nenhuma compra real foi feita automaticamente. O teste real deve conferir o preço
no checkout, concluir o pagamento voluntariamente e verificar a chegada do webhook.
Se o acesso não liberar, consulte bot_payment_events antes de tentar pagar de novo.

## Cupons e taxas do comprador

`supabase/payment_diagnostics.sql` atualiza a função existente para reconciliar
preço-base, desconto de cupom e acréscimos cobrados do comprador. São aceitos o
valor líquido do produto ou o total com acréscimos explicitamente informados pela
Cakto. Taxas de processamento do produtor (`fees`) não são usadas para completar
um valor divergente. Desconto sem cupom, base incorreta ou diferença sem explicação
continuam bloqueados. `payment_details` guarda apenas valores normalizados e IDs,
sem cartão, CPF, e-mail ou segredo do webhook. Eventos antigos sem esses campos
precisam ser reenviados a partir da compra real na Cakto; nunca sintetize uma
aprovação para liberar acesso. `tests/coupons.sql` valida os casos com rollback.
