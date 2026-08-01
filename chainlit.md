# Local Multimodal Agent

A local agent over Gemma 4 12B IT. Text, images and audio; five tools —
`list_files`, `read_file`, `write_file`, `remember_fact`, `search_memory`.

The filesystem tools see only the configured workspace, and `write_file` asks
you before it runs — if you close the tab first, the question is still there
when you come back. A fact is saved only when the agent calls `remember_fact`,
and it is found again in later conversations. Older turns are folded into a
rolling summary rather than dropped.

The conversation continues where the last one stopped.
