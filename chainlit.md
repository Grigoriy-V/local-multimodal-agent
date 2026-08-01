# Local Multimodal Agent

A local agent over Gemma 4 12B IT. Text, images and audio; five tools —
`list_files`, `read_file`, `write_file`, `remember_fact`, `search_memory`.

The filesystem tools see only the configured workspace, and `write_file` asks
you before it runs — if you close the tab first, the question is still there
when you come back. A fact is saved only when the agent calls `remember_fact`,
and it is found again in later conversations. Older turns are folded into a
rolling summary rather than dropped. The fold can react to the size of a
completed request in tokens reported by the model; recovery for a request that
is rejected before usage is reported is still being completed for Version 1.

The current startup conversation buttons are temporary while Version 1 is being
completed with normal persistent chat history. After each turn the agent says
how full the measured request was. Images and audio are supported; other inputs
must be refused clearly rather than silently ignored or sent as an empty turn.
