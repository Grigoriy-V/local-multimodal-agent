# Local Multimodal Agent

A local agent over Gemma 4 12B IT. Text, images and audio; five tools —
`list_files`, `read_file`, `write_file`, `remember_fact`, `search_memory`.

The filesystem tools see only the configured workspace, and `write_file` asks
you before it runs — if you close the tab first, the question is still there
when you come back. A fact is saved only when the agent calls `remember_fact`,
and it is found again in later conversations. Older turns are folded into a
rolling summary rather than dropped — by how large the request actually got, in
tokens the model counted itself, not by how many messages there are.

On start you are asked which conversation to open; answering nothing continues
the most recent one. After each turn the agent says how full the request was.
Attach an image or a sound and it will read it; attach anything else and it will
say so rather than ignore the file in silence.
