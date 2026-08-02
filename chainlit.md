# Local Multimodal Agent

A local multimodal agent over Gemma 4 12B IT with text, images, audio,
persistent conversations, governed filesystem tools, browser inspection,
long-term memory and controlled context.

Version 1 is the working chat baseline. Every ordinary request now enters one
autonomous natural-language interface: the model decides whether it needs a
direct answer or the bounded task lifecycle. Users approve scope or
consequential actions, not an agent mode or individual tool. Task-specific
semantic validation remains in development.

Filesystem access stays inside the configured workspace. Conversations and
memory survive application restarts, and older turns are summarized rather than
silently discarded.
