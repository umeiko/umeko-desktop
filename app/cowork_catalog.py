"""Built-in Cowork recipes and the capabilities available to custom roles."""

# The IDs are part of saved role configuration and the Pi tool allowlist.
TOOL_LABELS = {
    'web_search': ('网页搜索', 'Web search'),
    'web_fetch': ('网页读取', 'Read web pages'),
    'read': ('文件读取', 'Read files'),
    'find': ('查找文件', 'Find files'),
    'grep': ('搜索内容', 'Search files'),
    'write': ('写入文件', 'Write files'),
    'bash': ('运行命令', 'Run commands'),
    'powershell': ('PowerShell', 'PowerShell'),
    'ocr_image': ('图片文字识别', 'Image OCR'),
    'read_pdf_text': ('PDF 文字提取', 'Extract PDF text'),
    'analyze_image': ('辅助视觉', 'Auxiliary vision'),
    'image_gen': ('图像生成', 'Image generation'),
    'video_gen': ('视频生成', 'Video generation'),
    'submit_to_chatbox': ('提交成品', 'Deliver files'),
}

SKILL_LABELS = {
    'evidence-citations': ('来源与引文', 'Grounded citations', 'Nous Research · grounded-citations'),
    'office-artifacts': ('Microsoft Office', 'Microsoft Office', 'Nous Research · microsoft-office'),
    'pdf-paper-reading': ('论文 PDF 阅读', 'PDF paper reading', 'OpenAI Skills · pdf'),
    'document-to-action-items': ('从资料提取行动项', 'Document to action items', 'Nous Research · document-to-action-items'),
}
LEGACY_SKILLS = {'grounded-citations': 'evidence-citations', 'microsoft-office': 'office-artifacts', 'pdf': 'pdf-paper-reading'}

CONTEXTS = {
    'chat': ('对话', 'Conversation'),
    'files': ('对话与附件', 'Conversation and files'),
    'library': ('对话、附件与资料目录', 'Conversation, files and folders'),
}

CONTEXT_GUIDANCE = {
    'chat': 'Use the conversation and explicitly requested sources as the default context.',
    'files': 'Use the selected working directory and explicitly attached files for this task.',
    'library': 'Use the working directory, attached files and selected source folders. Read source materials without changing their contents.',
}

SUBAGENT_POOL = [
    dict(id='researcher', name=('资料研究员', 'Researcher'), description=('查找并核对资料来源', 'Find and verify sources'),
         prompt='Find relevant evidence and report findings with precise citations. Flag uncertainty and leave source material intact.',
         context='library', tools=['read', 'find', 'grep', 'ls', 'web_search', 'web_fetch'], skills=['evidence-citations']),
    dict(id='reviewer', name=('复核助手', 'Reviewer'), description=('检查结论、遗漏和矛盾', 'Check conclusions, omissions and contradictions'),
         prompt='Review the draft against the provided sources. Return concrete findings and suggested corrections. Preserve the original files.',
         context='files', tools=['read', 'find', 'grep', 'read_pdf_text'], skills=['evidence-citations']),
    dict(id='planner', name=('任务规划员', 'Planner'), description=('拆解目标和工作步骤', 'Break down goals and plan the work'),
         prompt='Turn the goal and existing decisions into a practical sequence of tasks. Identify dependencies and decisions that are still open.',
         context='chat', tools=['read'], skills=[]),
]


def recipe(identifier, icon, tone, name, description, prompt, starters, tools=(), skills=(), context='chat'):
    return dict(id=identifier, icon=icon, tone=tone, name=name, description=description, prompt=prompt,
                starters=starters, tools=list(tools), skills=list(skills), context=context, custom=False)


BUILTINS = [
    recipe('study', 'bulb', 'sage', ('Study Buddy', 'Study Buddy'),
           ('拆解难点，陪你练习和复盘。', 'Work through tricky concepts and check your understanding.'),
           'Tutor with worked examples and short recall exercises. Start with the learner’s goal. Offer hints before revealing answers when practicing. Cite retrieved sources for factual research.',
           [('用例子讲懂一个概念', 'Teach me a concept with an example'), ('根据我的笔记出三道练习题', 'Make three practice questions from my notes')],
           ('read', 'web_search', 'web_fetch'), ('evidence-citations',), 'files'),
    recipe('office', 'file', 'blue', ('文档生成', 'Office creator'),
           ('制作 Word 文档、Excel 表格和 PowerPoint 演示。', 'Create Word documents, Excel workbooks and PowerPoint decks.'),
           'Use the Microsoft Office Skill to create real .docx, .xlsx, or .pptx deliverables. Infer the requested output format, inspect attachments as needed, check the finished artifact and deliver it with submit_to_chatbox.',
           [('写一份项目进度报告（Word）', 'Write a project status report in Word'), ('做一份季度汇报（PowerPoint）', 'Make a quarterly review deck'), ('制作月度预算表（Excel）', 'Build a monthly budget in Excel')],
           ('read', 'write', 'bash', 'powershell', 'submit_to_chatbox'), ('office-artifacts',), 'files'),
    recipe('papers', 'globe', 'violet', ('论文翻译', 'Paper translator'),
           ('翻译 PDF 论文，保留结构、术语和页码。', 'Translate PDF papers while preserving structure, terms and page references.'),
           'Use read_pdf_text to extract the attached PDF page by page. Use the PDF Skill for more complex layouts or extraction fallbacks. Default to the user’s language when the source language differs. Preserve headings, equations, tables and citation markers. Add a short glossary and flag extraction uncertainty. For long papers translate in page ranges, offer a .md deliverable and submit completed files.',
           [('逐节翻译这篇 PDF 论文', 'Translate this PDF paper section by section'), ('先翻译摘要并整理术语表', 'Translate the abstract and build a glossary')],
           ('read_pdf_text', 'read', 'write', 'bash', 'powershell', 'submit_to_chatbox'), ('pdf-paper-reading',), 'files'),
    recipe('ocr', 'eye', 'amber', ('快速 OCR', 'Quick OCR'),
           ('使用会话右上角「本地 OCR」提取可复制的文字，不上传图片。', 'Use Local OCR in the conversation header to extract text without uploading images.'),
           'First use ocr_image on the attached file. Use visible image input or analyze_image if the local extractor is unavailable or if the layout needs interpretation. Preserve reading order, line breaks and table columns. Keep the original language and mark unreadable spans with [unclear]. If no image is available or the model cannot see it, explain that clearly.',
           [('提取这张图里的文字', 'Extract the text from this image'), ('把截图里的表格整理成 Markdown', 'Turn the table in this screenshot into Markdown')],
           ('ocr_image', 'analyze_image'), context='files'),
    recipe('knowledge', 'layers', 'teal', ('知识库洞察', 'Knowledge insights'),
           ('串联多份资料，找出共识、分歧和证据。', 'Find themes, disagreements and evidence across your sources.'),
           'Use only the source files or folders selected by the user. Locate likely sources before reading. Compare claims across documents, cite filenames and page or line references, expose conflicts and unanswered questions. Ask for source materials when none are attached.',
           [('从这些资料提炼关键结论', 'Find the main conclusions across these sources'), ('对比资料里的不同观点', 'Compare conflicting viewpoints in these sources')],
           ('read', 'find', 'grep', 'read_pdf_text'), ('evidence-citations', 'document-to-action-items'), 'library'),
    recipe('media', 'image', 'rose', ('图像与视频生成', 'Image and video studio'),
           ('用 Umeko 的生成模型，把创意变成图像或视频。', 'Turn an idea into an image or video with Umeko’s generation models.'),
           'Infer image or video from the request. Refine the description with subject, style and composition, adding motion and shot direction for video. Use image_gen or video_gen when configured. Tell the user where to configure generation if the required tool is missing. Report the actual generated media.',
           [('生成一张清晨海边的电影感图片', 'Generate a cinematic image of the coast at dawn'), ('生成一段城市夜景的短视频', 'Generate a short video of a city at night')],
           ('image_gen', 'video_gen')),
    recipe('data', 'grid', 'indigo', ('数据分析', 'Data analysis'),
           ('从 CSV 或 Excel 中发现趋势、异常和变化。', 'Find trends, outliers and changes in CSV or Excel data.'),
           'Inspect the schema and summarize missing values, duplicates and units before computing. Use reproducible calculations and verify totals. Explain assumptions, include relevant charts or a workbook when requested, and deliver output files with submit_to_chatbox.',
           [('分析这份表格的趋势和异常', 'Find trends and outliers in this spreadsheet'), ('按类别汇总数据并画图', 'Summarize the data by category and make a chart')],
           ('read', 'write', 'bash', 'powershell', 'submit_to_chatbox'), ('office-artifacts',), 'files'),
]
