"""
Tool selection module for optimising token usage.

This module implements intelligent tool selection to reduce the number
of tools sent with each API request, significantly reducing token consumption.
"""

import logging
from typing import List, Dict, Any, Set


class ToolSelector:
    """Selects relevant tools based on conversation context."""

    # Define tool categories and their associated tool name patterns
    TOOL_CATEGORIES = {
        'aws_security': ['prowler', 'scan', 'findings', 'security', 'compliance', 'vulnerability'],
        'docker': ['container', 'docker', 'image', 'compose', 'network', 'volume'],
        'documentation': ['note', 'obsidian', 'create_note', 'update_note', 'search_notes', 'vault'],
        'threat_intelligence': ['opencti', 'indicator', 'threat', 'malware', 'stix', 'observable'],
        'aws_infrastructure': ['ec2', 's3', 'lambda', 'cloudwatch', 'iam', 'vpc', 'rds', 'dynamodb', 'diagram'],
        'elasticsearch': ['elasticsearch', 'search', 'index', 'query', 'aggregation'],
        'ragstore': ['ragstore', 'rag', 'embedding', 'vector', 'semantic'],
        'documents': ['word', 'excel', 'powerpoint', 'pdf', 'document', 'docx', 'xlsx', 'pptx', 'spreadsheet'],
        'archives': ['archive', 'zip', 'tar', 'extract', 'compress', 'tgz'],
    }

    # Keywords in user messages that trigger specific categories
    CATEGORY_KEYWORDS = {
        'aws_security': ['security', 'prowler', 'scan', 'findings', 'vulnerabilities', 'compliance',
                        'threat', 'risk', 'audit', 'cis', 'benchmark'],
        'docker': ['container', 'docker', 'image', 'compose', 'containerised', 'containerized'],
        'documentation': ['note', 'obsidian', 'document', 'report', 'write', 'create note',
                         'update note', 'markdown', 'vault'],
        'threat_intelligence': ['threat', 'indicator', 'malware', 'opencti', 'ioc', 'attack',
                               'campaign', 'actor', 'ttp'],
        'aws_infrastructure': ['ec2', 's3', 'lambda', 'resource', 'aws', 'cloud', 'infrastructure',
                              'vpc', 'subnet', 'instance', 'bucket', 'function', 'diagram'],
        'elasticsearch': ['elasticsearch', 'search', 'query', 'index', 'log', 'aggregate'],
        'ragstore': ['ragstore', 'rag', 'embedding', 'semantic', 'vector', 'similarity'],
        'documents': ['document', 'word', 'excel', 'powerpoint', 'pdf', 'docx', 'xlsx', 'pptx',
                     'spreadsheet', 'presentation', 'template', 'office'],
        'archives': ['archive', 'zip', 'tar', 'extract', 'unzip', 'compressed', 'tgz'],
    }

    def __init__(self, max_tools_per_request: int = 30):
        """
        Initialise the tool selector.

        Args:
            max_tools_per_request: Maximum number of tools to include in a single request
        """
        self.max_tools_per_request = max_tools_per_request
        logging.info(f"ToolSelector initialised with max {max_tools_per_request} tools per request")

    def select_tools(self, all_tools: List[Dict[str, Any]], user_message: str,
                    conversation_history: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Select relevant tools based on user message and conversation context.

        Args:
            all_tools: List of all available tools
            user_message: The current user message
            conversation_history: Recent conversation messages

        Returns:
            List of selected tools
        """
        if not all_tools:
            logging.debug("No tools available for selection")
            return []

        # Always include built-in tools (they're small and always useful)
        selected_tools = [t for t in all_tools if t.get('server') == 'builtin']
        logging.debug(f"Included {len(selected_tools)} built-in tools")

        # Detect relevant categories based on user message and history
        relevant_categories = self._detect_categories(user_message, conversation_history)

        if not relevant_categories:
            logging.info("No specific tool categories detected, selecting diverse sample")
            return self._select_diverse_sample(all_tools, selected_tools)

        logging.info(f"Detected relevant categories: {relevant_categories}")

        # Build set of relevant tool name patterns
        relevant_patterns = set()
        for category in relevant_categories:
            relevant_patterns.update(self.TOOL_CATEGORIES.get(category, []))

        selected_tool_names = {t.get('name') for t in selected_tools}

        # Select tools matching the relevant patterns, then backfill to limit
        self._add_matching_tools(all_tools, selected_tools, selected_tool_names, relevant_patterns)
        self._backfill_tools(all_tools, selected_tools, selected_tool_names)

        logging.info(f"Selected {len(selected_tools)} tools from {len(all_tools)} available "
                     f"(categories: {', '.join(relevant_categories)})")
        self._log_selected_tools(selected_tools)

        return selected_tools

    def _add_matching_tools(self, all_tools: List[Dict[str, Any]],
                            selected: List[Dict[str, Any]],
                            selected_names: Set[str],
                            patterns: Set[str]) -> None:
        """Add tools whose name or description matches any of the given patterns."""
        for tool in all_tools:
            if len(selected) >= self.max_tools_per_request:
                break
            tool_name = tool.get('name', '')
            if tool_name in selected_names:
                continue
            tool_name_lower = tool_name.lower()
            tool_desc = tool.get('description', '').lower()
            if any(p in tool_name_lower or p in tool_desc for p in patterns):
                selected.append(tool)
                selected_names.add(tool_name)

    def _backfill_tools(self, all_tools: List[Dict[str, Any]],
                        selected: List[Dict[str, Any]],
                        selected_names: Set[str]) -> None:
        """Fill remaining slots up to max_tools_per_request with unselected tools."""
        if len(selected) >= self.max_tools_per_request:
            return
        remaining = self.max_tools_per_request - len(selected)
        logging.debug(f"Adding up to {remaining} additional tools to reach limit")
        for tool in all_tools:
            if len(selected) >= self.max_tools_per_request:
                break
            tool_name = tool.get('name', '')
            if tool_name not in selected_names:
                selected.append(tool)
                selected_names.add(tool_name)

    @staticmethod
    def _log_selected_tools(selected_tools: List[Dict[str, Any]]) -> None:
        """Log the names of selected tools for debugging."""
        tool_names = [t.get('name') for t in selected_tools]
        logging.debug(f"Selected tools: {', '.join(tool_names[:10])}{'...' if len(tool_names) > 10 else ''}")

    def _detect_categories(self, user_message: str,
                          conversation_history: List[Dict[str, Any]] = None) -> Set[str]:
        """
        Detect relevant tool categories from user message and history.

        Args:
            user_message: Current user message
            conversation_history: Recent conversation messages

        Returns:
            Set of relevant category names
        """
        categories = set()

        # Analyse user message
        self._match_categories(user_message.lower(), categories, source='user message')

        # Analyse recent conversation history (last 5 messages)
        if conversation_history:
            for msg in conversation_history[-5:]:
                content = self._extract_message_content(msg)
                self._match_categories(content, categories, source='conversation history')

        return categories

    def _match_categories(self, text: str, categories: Set[str], source: str) -> None:
        """Match keyword categories against text and add new matches to the set."""
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if category not in categories and any(kw in text for kw in keywords):
                categories.add(category)
                logging.debug(f"Category '{category}' detected from {source}")

    @staticmethod
    def _extract_message_content(msg) -> str:
        """Extract lowercased text content from a message (dict or string)."""
        if isinstance(msg, dict):
            return str(msg.get('content', '')).lower()
        return str(msg).lower()

    def _select_diverse_sample(self, all_tools: List[Dict[str, Any]],
                               already_selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Select a diverse sample of tools when no specific categories are detected.

        Attempts to get tools from each category to provide broad coverage.

        Args:
            all_tools: All available tools
            already_selected: Tools already selected (e.g., built-in tools)

        Returns:
            List of selected tools
        """
        selected = list(already_selected)
        selected_tool_names = {t.get('name') for t in selected}

        # Calculate how many tools to get from each category
        remaining_slots = self.max_tools_per_request - len(selected)
        tools_per_category = max(1, remaining_slots // len(self.TOOL_CATEGORIES))

        logging.debug(f"Selecting ~{tools_per_category} tools from each category for diversity")

        for category, category_patterns in self.TOOL_CATEGORIES.items():
            if len(selected) >= self.max_tools_per_request:
                break
            self._add_category_tools(
                all_tools, selected, selected_tool_names,
                category_patterns, tools_per_category,
            )

        # Backfill any remaining slots
        self._backfill_tools(all_tools, selected, selected_tool_names)

        logging.info(f"Selected {len(selected)} diverse tools (no specific category detected)")
        return selected

    def _add_category_tools(self, all_tools: List[Dict[str, Any]],
                            selected: List[Dict[str, Any]],
                            selected_names: Set[str],
                            patterns: List[str],
                            max_count: int) -> None:
        """Add up to max_count tools matching the given category patterns."""
        added = 0
        for tool in all_tools:
            if added >= max_count or len(selected) >= self.max_tools_per_request:
                break
            tool_name = tool.get('name', '')
            if tool_name in selected_names:
                continue
            tool_name_lower = tool_name.lower()
            tool_desc = tool.get('description', '').lower()
            if any(p in tool_name_lower or p in tool_desc for p in patterns):
                selected.append(tool)
                selected_names.add(tool_name)
                added += 1
