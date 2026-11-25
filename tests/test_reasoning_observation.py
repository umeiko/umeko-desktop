"""Response evidence used by background effect discovery."""
import unittest

from app.reasoning_observation import observe_reasoning


class ReasoningObservationTests(unittest.TestCase):
    def test_usage_snapshots_take_precedence_without_adding_them(self):
        events = [
            {'choices': [{'delta': {'reasoning_content': 'step', 'reasoning': 'step'}}]},
            {'usage': {'completion_tokens_details': {'reasoning_tokens': 12}}},
            {'usage': {'completion_tokens_details': {'reasoning_tokens': 12}},
             'choices': [{'delta': {'content': '42'}, 'finish_reason': 'stop'}]},
        ]
        result = observe_reasoning(events, lambda value: value == '42')
        self.assertEqual(result['reasoningTokens'], 12)
        self.assertEqual(result['thinkingChars'], 4)
        self.assertTrue(result['correct'])
        self.assertEqual(result['finishReason'], 'stop')

    def test_split_think_tags_and_hidden_reasoning(self):
        events = [{'choices': [{'delta': {'content': chunk}}]}
                  for chunk in ['<thi', 'nk>calculate', '</think>', '42']]
        result = observe_reasoning(events, lambda value: value == '42')
        self.assertEqual(result['thinkingChars'], 9)
        self.assertEqual(result['answer'], '42')
        hidden = observe_reasoning([{'choices': [{'message': {'content': '42'}}]}], lambda value: True)
        self.assertIsNone(hidden['reasoningTokens'])
        self.assertEqual(hidden['thinkingChars'], 0)


if __name__ == '__main__':
    unittest.main()
