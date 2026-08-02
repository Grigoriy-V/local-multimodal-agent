# Local Multimodal Agent

A local multimodal agent over Gemma 4 12B IT with text, images, audio,
persistent conversations, governed filesystem tools, browser inspection,
long-term memory and controlled context.

Version 1 is the working chat baseline. Version 1.5 is developing one autonomous
natural-language interface: the model decides whether a request needs a direct
answer or planning, tools and validation. Users approve scope or consequential
actions, not an agent mode or individual tool.

Filesystem access stays inside the configured workspace. Conversations and
memory survive application restarts, and older turns are summarized rather than
silently discarded.
