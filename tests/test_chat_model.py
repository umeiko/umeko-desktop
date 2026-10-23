import copy
import unittest

from app.chat_model import ChatModel


class ChatModelTests(unittest.TestCase):
    def test_length_continuations_keep_markdown_and_completed_tools_intact(self):
        messages = [
            {'role':'assistant', 'text':'Inspect', 'tools':[{'id':'one'}]},
            {'role':'assistant', 'thinking':'plan', 'text':'```rust\nfn ma', 'stopReason':'length'},
            {'role':'assistant', 'thinking':'check', 'text':'in() {}\n```', 'stopReason':'stop'},
        ]
        original = copy.deepcopy(messages)
        row = ChatModel.project(messages)[0]
        self.assertEqual(row['text'], '```rust\nfn main() {}\n```')
        self.assertEqual([s['kind'] for s in row['activity']], ['text','tools','thinking','text'])
        self.assertEqual(row['activity'][-1]['text'], row['text'])
        self.assertEqual(row['activity'][-2]['text'], 'plancheck')
        self.assertEqual(messages, original)
        self.assertEqual(len(ChatModel.project([
            {'role':'assistant','text':'partial','stopReason':'length'},
            {'role':'user','text':'different task'},
            {'role':'assistant','text':'new answer'}])), 3)

    def test_questions_use_display_rows_and_do_not_refresh_during_streaming(self):
        from app.message_attachments import attachment_prompt
        model = ChatModel()
        changes = []
        model.questionsChanged.connect(lambda: changes.append(1))
        messages = [
            {'role':'user','text':'  First\nquestion  '},
            {'role':'assistant','text':'inspect','tools':[{'id':'read'}]},
            {'role':'assistant','text':'answer'},
            {'role':'user','text':attachment_prompt('', [{'kind':'file','path':'/tmp/report.pdf'}])},
            {'role':'assistant','text':''},
        ]
        model.update(messages)
        self.assertEqual(model.questions, [{'row':0,'title':'First question'}, {'row':2,'title':'report.pdf'}])
        for i in range(50):
            messages[-1]['text'] += ' streamed'
            model.update(messages)
        self.assertEqual(len(changes), 1)
        messages[0]['text'] = 'Edited question'
        model.update(messages)
        self.assertEqual(model.questions[0]['title'], 'Edited question')
        model.update([])
        self.assertEqual(model.questions, [])

    def test_attachment_tags_project_old_history_without_altering_native_prompt(self):
        from app.message_attachments import attachment_prompt
        raw = attachment_prompt("Describe these files", [{"kind":"file", "path":r"D:\fixture\Kimi Code.lnk"}, {"kind":"folder", "path":"/tmp/example folder"}])
        rows = ChatModel.project([{"role":"user", "text":raw}])
        self.assertEqual(rows[0]["text"], "Describe these files")
        self.assertEqual([a["name"] for a in rows[0]["attachments"]], ["Kimi Code.lnk", "example folder"])
        self.assertEqual(rows[0]["attachments"][0]["path"], r"D:\fixture\Kimi Code.lnk")
        self.assertIn("附件（用户提供的路径", raw)
        only = ChatModel.project([{"role":"user", "text":attachment_prompt("", [{"kind":"image", "path":"/tmp/picture.png"}])}])[0]
        self.assertEqual(only["text"], "")
        self.assertEqual(only["attachments"][0]["name"], "picture.png")
        malformed = raw + "\nThis extra paragraph must remain visible."
        self.assertEqual(ChatModel.project([{"role":"user", "text":malformed}])[0]["text"], malformed)
        self.assertEqual(ChatModel.project([{"role":"assistant", "text":raw}])[0]["text"], raw)

    def test_tool_sequence_is_one_display_row_without_changing_native_messages(self):
        messages = [
            {"role": "user", "text": "task"},
            {"role": "assistant", "text": "Inspecting files", "tools": [{"id": "one", "name": "read", "state": "done"}]},
            {"role": "assistant", "text": "Updating file", "tools": [{"id": "two", "name": "write", "state": "running"}]},
            {"role": "assistant", "text": "Completed"},
            {"role": "user", "text": "next task"},
        ]
        original = copy.deepcopy(messages)
        model = ChatModel()
        model.update(messages)
        self.assertEqual(len(model.rows), 3)
        self.assertEqual(model.rows[1]["text"], "Completed")
        activity = model.rows[1]["activity"]
        self.assertEqual([step["kind"] for step in activity], ["text", "tools", "text", "tools", "text"])
        self.assertEqual([step["text"] for step in activity if step["kind"] == "text"], ["Inspecting files", "Updating file", "Completed"])
        self.assertEqual(messages, original)
        messages[2]["tools"][0]["state"] = "done"
        model.update(messages)
        self.assertEqual(len(model.rows), 3)
        self.assertEqual(model.rows[1]["tools"][1]["state"], "done")

    def test_reasoning_and_adjacent_tools_preserve_order_and_stable_offsets(self):
        messages = [
            {"role": "assistant", "thinking": "Check fixtures", "text": "I will run the checks.", "tools": [{"id": "a", "state": "running"}]},
            {"role": "assistant", "text": "", "tools": [{"id": "b", "state": "error"}]},
            {"role": "assistant", "thinking": "Compare the output", "text": "Fixed."},
        ]
        model = ChatModel()
        model.update(messages)
        self.assertEqual(len(model.rows), 1)
        activity = model.rows[0]["activity"]
        self.assertEqual([s["kind"] for s in activity], ["thinking", "text", "tools", "thinking", "text"])
        self.assertEqual([t["id"] for t in activity[2]["tools"]], ["a", "b"])
        self.assertEqual([s["blockOffset"] for s in activity], [0, 10000, 20000, 30000, 40000])
        messages[2]["text"] += " More output."
        model.update(messages)
        self.assertEqual([s["blockOffset"] for s in model.rows[0]["activity"]], [s["blockOffset"] for s in activity])
        self.assertEqual(model.rows[0]["activity"][-1]["text"], "Fixed. More output.")

    def test_reasoning_only_and_no_reasoning_are_distinct(self):
        rows = ChatModel.project([{"role": "assistant", "text": "", "thinking": "Native reasoning"}, {"role": "user", "text": "next"}, {"role": "assistant", "text": "Answer"}])
        self.assertEqual(rows[0]["activity"][0]["kind"], "thinking")
        self.assertEqual(rows[2]["activity"], [{"kind": "text", "text": "Answer", "error": False, "blockOffset": 0}])
