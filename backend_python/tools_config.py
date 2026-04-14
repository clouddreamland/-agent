import json

TEACHING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_ppt",
            "description": "【仅当用户明确要求生成PPT、幻灯片或演示文稿时才调用】。注意：教案、教学设计、教学计划、讲课稿等纯文字内容不属于PPT，不要调用此工具，直接用文字回复即可。必须提取用户要求的主题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "PPT的核心主题或知识点，例如：'光合作用的过程'"
                    },
                    "pages": {
                        "type": "integer",
                        "description": "用户要求的页数。如果用户没说，默认为 3"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_ppt",
            "description": "当用户对已有课件提出修改意见、调整建议或迭代需求时，调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "feedback": {
                        "type": "string",
                        "description": "用户提出的具体修改意见"
                    }
                },
                "required": ["feedback"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_ppt",
            "description": "当用户确认课件内容无误，明确要求导出、下载或生成最终PPT文件时，调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_word_lesson_plan",
            "description": "【仅当用户明确要求生成教案、教学设计、教学方案或教案文档时才调用】。生成一份包含教学目标、教学过程、教学方法、课堂活动设计、课后作业五大模块的详细Word教案文档。注意：如果用户要求生成PPT/幻灯片，不要调用此工具，应调用generate_ppt。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "教案的核心教学主题，例如：'望庐山瀑布' 或 '光合作用的过程'"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_html5_interactive",
            "description": "【当用户要求生成互动小游戏、动画创意、课堂互动活动、HTML5互动内容、趣味练习或知识闯关时调用】。生成一个可在浏览器中直接运行的HTML5单页互动小游戏或动画演示。注意：如果用户要求生成PPT则调用generate_ppt，不要调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "互动内容围绕的核心知识点或教学主题，例如：'九九乘法表' 或 '太阳系八大行星'"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_textbook",
            "description": "当学生询问具体的学术知识点时调用，用于从教材知识库中检索权威答案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "学生询问的知识点关键词或问题，例如：'牛顿第二定律' 或 '光合作用的原理'"
                    }
                },
                "required": ["query"]
            }
        }
    }
]
