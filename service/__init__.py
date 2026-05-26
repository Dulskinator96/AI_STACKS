"""service — FastAPI surface over the TASKMASTER Ω kernel.

The API is a thin visualization/transport layer. The kernel is the true
system; every endpoint delegates into kernel.* and engine.* — none owns its
own orchestration, memory, or truth.
"""
