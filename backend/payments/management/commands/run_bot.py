import asyncio
import logging
import signal

from django.conf import settings
from telegram._files.inputfile import InputFile
from django.core.management.base import BaseCommand

from payments.bi_telegram_bot import handle_message, handle_message_with_media

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start the Telegram Business Intelligence bot (polling or webhook)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--webhook',
            type=str,
            default=None,
            help='Set webhook URL and run in webhook mode (e.g. https://example.com/api/v1/telegram/webhook/)',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        if not token:
            self.stderr.write(self.style.ERROR(
                'TELEGRAM_BOT_TOKEN not set. Add it to your .env file.'
            ))
            return

        webhook_url = options.get('webhook')
        if webhook_url:
            self._setup_webhook(token, webhook_url)
        else:
            self.stdout.write(self.style.SUCCESS('Starting Telegram BI bot (polling mode)...'))
            asyncio.run(self._run_polling(token))

    def _setup_webhook(self, token: str, webhook_url: str):
        import httpx
        resp = httpx.post(
            f'https://api.telegram.org/bot{token}/setWebhook',
            json={'url': webhook_url, 'allowed_updates': ['message']},
        )
        data = resp.json()
        if data.get('ok'):
            self.stdout.write(self.style.SUCCESS(
                f'Webhook set to {webhook_url}. Bot will respond via the Django webhook endpoint.'
            ))
            self.stdout.write(self.style.WARNING(
                'Make sure the webhook URL is publicly accessible and TELEGRAM_WEBHOOK_SECRET is configured if needed.'
            ))
        else:
            self.stderr.write(self.style.ERROR(f'Failed to set webhook: {data}'))

    async def _run_polling(self, token: str):
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        application = Application.builder().token(token).build()

        _COMMANDS = [
            'start', 'help', 'briefing', 'revenue', 'sales', 'stock', 'recon',
            'recon_deep',
            'merch', 'compare', 'trend', 'anomalies', 'branches', 'vs',
            'inventory', 'stock_by_category', 'pending', 'pipeline',
            'month', 'year', 'product_stock', 'product_sales', 'product_trend',
            'product_compare', 'top', 'top_revenue', 'category',
            'txn', 'txn_detail', 'customer', 'user', 'gateways', 'combined',
            'movements', 'pv', 'cost', 'kits', 'search',
        ]

        MAX_MSG_LEN = 4000  # leave headroom under Telegram's 4096 limit

        async def _send_long_message(update: Update, text: str):
            """Send a message, splitting into multiple chunks if too long."""
            if len(text) <= MAX_MSG_LEN:
                try:
                    await update.message.reply_text(text, parse_mode='Markdown')
                except Exception:
                    await update.message.reply_text(text)
                return

            chunks = []
            while text:
                if len(text) <= MAX_MSG_LEN:
                    chunks.append(text)
                    break

                split_at = text.rfind('\n', 0, MAX_MSG_LEN)
                if split_at == -1:
                    split_at = text.rfind('. ', 0, MAX_MSG_LEN)
                if split_at == -1:
                    split_at = text.rfind(', ', 0, MAX_MSG_LEN)
                if split_at == -1:
                    split_at = MAX_MSG_LEN

                chunk = text[:split_at + 1].strip()
                text = text[split_at + 1:].strip()
                if chunk:
                    chunks.append(chunk)

            if text.strip():
                chunks.append(text.strip())

            for chunk in chunks:
                if not chunk:
                    continue
                try:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
                except Exception:
                    await update.message.reply_text(chunk)

        async def _reply(update: Update, text: str):
            await _send_long_message(update, text)

        async def generic_handler(update: Update, context):
            user_id = update.effective_user.id if update.effective_user else None
            cmd = update.message.text.strip().lower()
            if context.args:
                cmd += ' ' + ' '.join(context.args)
            response, chart_buf, xlsx_buf, xlsx_name = await handle_message_with_media(cmd, user_id)
            if response:
                await _reply(update, response)
            if chart_buf:
                try:
                    await update.message.reply_photo(
                        InputFile(chart_buf.getvalue(), filename='recon_chart.png')
                    )
                except Exception as e:
                    logger.warning(f"Failed to send chart: {e}")
                    await _reply(update, "❌ Could not generate chart image.")
            if xlsx_buf and xlsx_name:
                try:
                    await update.message.reply_document(
                        InputFile(xlsx_buf.getvalue(), filename=xlsx_name)
                    )
                except Exception as e:
                    logger.warning(f"Failed to send XLSX: {e}")
                    await _reply(update, "❌ Could not generate XLSX report.")

        CHART_KEYWORDS = ['chart', 'graph', 'png', 'visual', 'picture', 'image', 'plot']

        async def free_form(update: Update, context):
            user_id = update.effective_user.id if update.effective_user else None
            text = update.message.text
            wants_chart = any(kw in text.lower() for kw in CHART_KEYWORDS)
            cmd = text + (' --chart' if wants_chart else '')
            response, chart_buf, xlsx_buf, xlsx_name = await handle_message_with_media(cmd, user_id)
            if response:
                await _reply(update, response)
            if chart_buf:
                try:
                    await update.message.reply_photo(
                        InputFile(chart_buf.getvalue(), filename='chart.png')
                    )
                except Exception as e:
                    logger.warning(f"Failed to send chart: {e}")
                    await _reply(update, "❌ Could not generate chart image.")
            if xlsx_buf and xlsx_name:
                try:
                    await update.message.reply_document(
                        InputFile(xlsx_buf.getvalue(), filename=xlsx_name)
                    )
                except Exception as e:
                    logger.warning(f"Failed to send XLSX: {e}")
                    await _reply(update, "❌ Could not generate XLSX report.")

        for cmd in _COMMANDS:
            application.add_handler(CommandHandler(cmd, generic_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_form))

        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        stop_signal = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_signal.set)
            except NotImplementedError:
                pass

        self.stdout.write(self.style.SUCCESS('Bot is running and polling for updates. Press Ctrl+C to stop.'))
        await stop_signal.wait()

        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        self.stdout.write(self.style.SUCCESS('Bot stopped.'))
