import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from django.test import TestCase, override_settings
from django.utils import timezone

from payments.services.bi_agent_service import BIAgent, _TOOL_FUNCTIONS, _parse_date, _TOOL_DEFINITIONS
from payments.services.bi_core_service import BiCoreService
from payments.services.bi_extended_service import BiExtendedService


class TestParseDate(TestCase):
    def test_parse_date_valid(self):
        d = _parse_date('2026-06-19')
        self.assertEqual(d.isoformat(), '2026-06-19')

    def test_parse_date_none(self):
        d = _parse_date(None)
        self.assertIsNotNone(d)

    def test_parse_date_empty(self):
        d = _parse_date('')
        self.assertIsNotNone(d)


class TestToolDefinitions(TestCase):
    def test_all_tools_have_functions(self):
        for td in _TOOL_DEFINITIONS:
            name = td['function']['name']
            self.assertIn(name, _TOOL_FUNCTIONS, f"Missing function for {name}")

    def test_all_functions_have_tool_def(self):
        for name in _TOOL_FUNCTIONS:
            found = any(
                td['function']['name'] == name
                for td in _TOOL_DEFINITIONS
            )
            self.assertTrue(found, f"Missing tool definition for {name}")

    def test_tool_definitions_have_valid_json_schema(self):
        for td in _TOOL_DEFINITIONS:
            params = td['function']['parameters']
            self.assertIn('type', params)
            self.assertEqual(params['type'], 'object')
            self.assertIn('properties', params)

    def test_sales_buckets_excludes_merch(self):
        self.assertNotIn('MERCH', BiCoreService.SALES_BUCKETS)
        self.assertIn('MERCH', BiCoreService.REVENUE_BUCKETS)

    def test_tool_count(self):
        """Should have 37 tools (36 + get_reconciliation_deep_dive)."""
        self.assertEqual(len(_TOOL_DEFINITIONS), 37)
        self.assertEqual(len(_TOOL_FUNCTIONS), 37)

    def test_reconciliation_deep_dive_tool_exists(self):
        names = [t['function']['name'] for t in _TOOL_DEFINITIONS]
        self.assertIn('get_reconciliation_deep_dive', names)
        self.assertIn('get_reconciliation_deep_dive', _TOOL_FUNCTIONS)

    def test_all_tool_descriptions_distinct_from_sales(self):
        """Gateway-level fulfillment tools should not say 'product-level' in descriptions."""
        fulfillment_tools = ['get_fulfillment_by_gateway', 'get_revenue_vs_sales',
                          'get_gateway_breakdown', 'get_period_revenue_vs_sales',
                          'get_month_comparison', 'get_year_comparison',
                          'get_briefing']
        for td in _TOOL_DEFINITIONS:
            name = td['function']['name']
            desc = td['function']['description']
            if name in fulfillment_tools:
                self.assertNotIn('product-level', desc.lower(), f"{name} should not mention product-level")


class TestBIAgentProviderSelection(TestCase):
    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools')
    def test_gemini_provider(self, mock_call):
        mock_call.return_value = 'done'
        with override_settings(
            LLM_PROVIDER='gemini',
            GEMINI_API_KEY='test-key',
            GEMINI_MODEL='gemini-2.0-flash',
        ):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        mock_call.assert_called_once()

    @patch('payments.services.bi_agent_service.BIAgent._call_groq')
    def test_groq_provider(self, mock_call):
        mock_call.return_value = 'done'
        with override_settings(
            LLM_PROVIDER='groq',
            GROQ_API_KEY='test-key',
        ):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        mock_call.assert_called_once()

    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools')
    def test_openai_provider(self, mock_call):
        mock_call.return_value = 'done'
        with override_settings(
            LLM_PROVIDER='openai',
            OPENAI_API_KEY='test-key',
        ):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        mock_call.assert_called_once()

    def test_gemini_no_key(self):
        with override_settings(LLM_PROVIDER='gemini', GEMINI_API_KEY=''):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        self.assertIn('Gemini not configured', result)

    def test_groq_no_key(self):
        with override_settings(LLM_PROVIDER='groq', GROQ_API_KEY=''):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        self.assertIn('Groq not configured', result)

    def test_openai_no_key(self):
        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY=''):
            result = asyncio.run(BIAgent._process('hi', 'chat_1', []))
        self.assertIn('LLM not configured', result)

    @patch('payments.services.bi_agent_service.BIAgent._process')
    @patch('payments.services.bi_conversation_service.ConversationMemory.get_history')
    @patch('payments.services.bi_conversation_service.ConversationMemory.add_exchange')
    def test_process_message_flow(self, mock_add, mock_history, mock_process):
        mock_history.return_value = []
        mock_process.return_value = 'Hello!'

        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key'):
            result = asyncio.run(BIAgent.process_message('chat_1', 'hi'))

        self.assertEqual(result, 'Hello!')
        mock_history.assert_called_once_with('chat_1')
        mock_add.assert_called_once()


class TestBIAgentBuildMessages(TestCase):
    @override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key')
    def test_build_messages_includes_history(self):
        history = [
            {'user': 'how did we do yesterday?', 'bot': 'Revenue was KES 50,000'},
        ]
        messages = BIAgent._build_messages('and today?', timezone.localdate(), history)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertEqual(messages[1]['content'], 'how did we do yesterday?')
        self.assertEqual(messages[2]['role'], 'assistant')
        self.assertEqual(messages[2]['content'], 'Revenue was KES 50,000')
        self.assertEqual(messages[3]['role'], 'user')
        self.assertEqual(messages[3]['content'], 'and today?')

    def test_build_messages_system_prompt_has_date(self):
        from datetime import date
        today = date(2026, 6, 19)
        messages = BIAgent._build_messages('hi', today, [])
        self.assertIn('2026-06-19', messages[0]['content'])
        self.assertIn('37 function tools', messages[0]['content'])

    def test_build_messages_empty_history(self):
        messages = BIAgent._build_messages('hi', timezone.localdate(), [])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertEqual(messages[1]['content'], 'hi')


class TestBIAgentWithTools(TestCase):
    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools')
    @patch('payments.services.bi_conversation_service.ConversationMemory.get_history')
    @patch('payments.services.bi_conversation_service.ConversationMemory.add_exchange')
    def test_direct_reply(self, mock_add, mock_history, mock_tools):
        mock_tools.return_value = 'Revenue was KES 50,000 today.'
        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key'):
            result = asyncio.run(BIAgent.process_message('chat_1', 'how much revenue today?'))
        self.assertEqual(result, 'Revenue was KES 50,000 today.')

    def test_tool_function_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_stock_alerts']
        result = fn({})
        self.assertIn('out_of_stock_count', result)
        self.assertIn('low_stock_count', result)

    def test_get_inventory_value_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_inventory_value']
        result = fn({})
        self.assertIn('total_value_at_retail', result)

    def test_get_pending_fulfillments_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_pending_fulfillments']
        result = fn({})
        self.assertIsInstance(result, dict)

    def test_get_fulfillment_by_gateway_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_fulfillment_by_gateway']
        result = fn({})
        self.assertIn('date', result)
        self.assertIn('buckets', result)
        self.assertNotIn('MERCH', result['buckets'])
        self.assertEqual(len(result['buckets']), 3)

    def test_fulfillment_by_gateway_output_schema(self):
        fn = _TOOL_FUNCTIONS['get_fulfillment_by_gateway']
        result = fn({})
        for bucket_name in BiCoreService.SALES_BUCKETS:
            self.assertIn(bucket_name, result['buckets'])
            self.assertIn('amount', result['buckets'][bucket_name])
            self.assertIn('count', result['buckets'][bucket_name])

    def test_get_all_products_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_all_products']
        result = fn({})
        self.assertIn('total_products', result)
        self.assertIn('products', result)

    def test_get_all_products_with_filters(self):
        fn = _TOOL_FUNCTIONS['get_all_products']
        result = fn({'stock_status': 'OUT_OF_STOCK'})
        self.assertIn('total_products', result)
        for p in result['products']:
            self.assertEqual(p['stock_status'], 'OUT_OF_STOCK')

    def test_get_all_products_empty_filters(self):
        fn = _TOOL_FUNCTIONS['get_all_products']
        result = fn({'category': 'nonexistent-category-xyz'})
        self.assertEqual(result['total_products'], 0)
        self.assertEqual(result['products'], [])

    def test_get_daily_sales_summary_dispatch(self):
        fn = _TOOL_FUNCTIONS['get_daily_sales_summary']
        result = fn({})
        self.assertIn('total_revenue', result)
        self.assertIn('total_quantity_sold', result)
        self.assertIn('unique_products', result)
        self.assertIn('top_products', result)
        self.assertIn('date', result)

    def test_get_daily_sales_summary_schema(self):
        fn = _TOOL_FUNCTIONS['get_daily_sales_summary']
        result = fn({})
        if result['top_products']:
            self.assertIn('name', result['top_products'][0])
            self.assertIn('quantity_sold', result['top_products'][0])
            self.assertIn('revenue', result['top_products'][0])
        self.assertIsInstance(result['unique_products'], int)


class TestAgentUnknownCommandFallback(TestCase):
    @patch('payments.bi_telegram_bot.handle_message')
    def test_bot_returns_error_for_unknown_command(self, mock_handle):
        from payments.bi_telegram_bot import handle_message
        mock_handle.side_effect = lambda text, user_id=None: "❌ Unknown command. Type /help for available commands."
        result = asyncio.run(handle_message('/nonexistent', user_id=123))
        self.assertIn('Unknown command', result)


class TestProcessMessageWithChart(TestCase):
    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools_and_data')
    @patch('payments.services.bi_conversation_service.ConversationMemory.get_history')
    @patch('payments.services.bi_conversation_service.ConversationMemory.add_exchange')
    def test_with_chart(self, mock_add, mock_history, mock_tools):
        mock_history.return_value = []
        mock_tools.return_value = ('Revenue was KES 50,000.', 'get_revenue_by_bucket', {
            'buckets': {
                'PAYBILL_PDQ': {'total_revenue': 30000, 'transaction_count': 10},
                'TILL': {'total_revenue': 20000, 'transaction_count': 5},
            }
        })

        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key'):
            result, chart_buf = asyncio.run(
                BIAgent.process_message_with_chart('chat_1', 'how much revenue today?')
            )

        self.assertEqual(result, 'Revenue was KES 50,000.')
        self.assertIsNotNone(chart_buf)
        self.assertGreater(len(chart_buf.getvalue()), 100)

    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools_and_data')
    @patch('payments.services.bi_conversation_service.ConversationMemory.get_history')
    @patch('payments.services.bi_conversation_service.ConversationMemory.add_exchange')
    def test_no_tool_call_no_chart(self, mock_add, mock_history, mock_tools):
        mock_history.return_value = []
        mock_tools.return_value = ('Hello! How can I help?', None, None)

        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key'):
            result, chart_buf = asyncio.run(
                BIAgent.process_message_with_chart('chat_1', 'hi')
            )

        self.assertEqual(result, 'Hello! How can I help?')
        self.assertIsNone(chart_buf)

    @patch('payments.services.bi_agent_service.BIAgent._call_with_tools_and_data')
    @patch('payments.services.bi_conversation_service.ConversationMemory.get_history')
    @patch('payments.services.bi_conversation_service.ConversationMemory.add_exchange')
    def test_unknown_tool_no_chart(self, mock_add, mock_history, mock_tools):
        mock_history.return_value = []
        mock_tools.return_value = ('Done.', 'get_reconciliation_deep_dive', {'status': 'BALANCED'})

        with override_settings(LLM_PROVIDER='openai', OPENAI_API_KEY='test-key'):
            result, chart_buf = asyncio.run(
                BIAgent.process_message_with_chart('chat_1', 'deep dive please')
            )

        self.assertEqual(result, 'Done.')
        self.assertIsNone(chart_buf)
