# Local Multimodal Agent

A local agent over Gemma 4 12B IT. Text, images and audio; four tools —
`list_files`, `read_file`, `remember_fact`, `search_memory`.

The filesystem tools see only the configured workspace. A fact is saved only
when the agent calls `remember_fact`, and it is found again in later
conversations. Older turns are folded into a rolling summary rather than
dropped.

The conversation continues where the last one stopped.
