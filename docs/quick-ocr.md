# Quick OCR in Cowork

Choose **Quick OCR** in Cowork, attach a local image and send it in the
conversation. Quick OCR uses your selected chat model to follow the
`local-image-ocr` skill. The conversation passes a local file path. The
skill runs recognition on the original image with RapidOCR and ONNX Runtime
on CPU, and uses the resulting text to answer in the same conversation.

On the first image request, the coworker checks for Python 3.12 and prepares
a virtual environment in `./.umeko/quick-ocr` in that Cowork workspace. An
existing `uv` installation can supply Python when needed. The first setup
needs access to the Python package source and uses the current tool approval
settings. The coworker reuses a working environment on subsequent requests,
and recognition itself works offline. Processing the response still uses
your selected chat model.

The image stays on the machine. The attachment path and recognized text
can be visible to the selected model provider. If OCR cannot run locally,
the skill reports the reason in the same conversation.
