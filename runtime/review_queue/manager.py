"""Review Queue Manager — inbox triage backend for NCL pipeline.

Aggregates pending items from pumps, governance actions, and council sessions
into a unified inbox with batch operations, tagging, linking, and archiving.
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ReviewItemType(str, Enum):
    """Types of items in the review queue."""
    PUMP = "PUMP"
    ACTION = "ACTION"
    COUNCIL = "COUNCIL"
    MANDATE = "MANDATE"


class UrgencyLevel(str, Enum):
    """Urgency levels for items."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Suggestion(BaseModel):
    """AI-generated suggestion for an item."""
    suggestion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_text: str
    action_type: str  # approve, reject, defer, escalate, tag
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ReviewItem(BaseModel):
    """A single item in the review queue."""
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_type: ReviewItemType
    title: str
    description: str
    urgency: UrgencyLevel = UrgencyLevel.NORMAL
    source_agent: str  # e.g., "First Strike", "Governance", "Council"
    source_id: str  # pump_id, action_id, session_id, etc.
    payload: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    linked_items: List[str] = Field(default_factory=list)
    suggestions: List[Suggestion] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    archived: bool = False
    archived_at: Optional[str] = None


class BatchOperation(BaseModel):
    """Batch operation on multiple items."""
    operation: str  # tag, link, archive, approve, reject
    item_ids: List[str]
    params: Dict[str, Any] = Field(default_factory=dict)


class ReviewQueueManager:
    """Manages review queue inbox for NCL pipeline."""

    def __init__(self, data_dir: str = "/tmp/ncl_review_queue"):
        """Initialize review queue manager.

        Args:
            data_dir: Directory to store review queue state
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # State file paths
        self.items_path = self.data_dir / "items.jsonl"
        self.tags_path = self.data_dir / "tags.json"
        self.links_path = self.data_dir / "links.json"
        self.archive_path = self.data_dir / "archive.jsonl"
        self.suggestions_path = self.data_dir / "suggestions.json"

        # In-memory state
        self.items: Dict[str, ReviewItem] = {}
        self.tag_assignments: Dict[str, List[str]] = {}
        self.item_links: Dict[str, List[str]] = {}
        self.archived: Dict[str, ReviewItem] = {}
        self.cached_suggestions: Dict[str, List[Suggestion]] = {}

    async def init(self):
        """Load state from disk."""
        self._load_items()
        self._load_tags()
        self._load_links()
        self._load_archive()

    def _load_items(self):
        """Load items from jsonl file."""
        if self.items_path.exists():
            with open(self.items_path, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        item = ReviewItem(**data)
                        self.items[item.item_id] = item

    def _load_tags(self):
        """Load tag assignments from json file."""
        if self.tags_path.exists():
            with open(self.tags_path, 'r') as f:
                self.tag_assignments = json.load(f)

    def _load_links(self):
        """Load item links from json file."""
        if self.links_path.exists():
            with open(self.links_path, 'r') as f:
                self.item_links = json.load(f)

    def _load_archive(self):
        """Load archived items from jsonl file."""
        if self.archive_path.exists():
            with open(self.archive_path, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        item = ReviewItem(**data)
                        self.archived[item.item_id] = item

    def _save_items(self):
        """Save items to jsonl file."""
        with open(self.items_path, 'w') as f:
            for item in self.items.values():
                f.write(item.model_dump_json() + '\n')

    def _save_tags(self):
        """Save tag assignments to json file."""
        with open(self.tags_path, 'w') as f:
            json.dump(self.tag_assignments, f, indent=2)

    def _save_links(self):
        """Save item links to json file."""
        with open(self.links_path, 'w') as f:
            json.dump(self.item_links, f, indent=2)

    def _save_archive(self):
        """Save archived items to jsonl file."""
        with open(self.archive_path, 'w') as f:
            for item in self.archived.values():
                f.write(item.model_dump_json() + '\n')

    async def ingest_pump(self, pump_data: dict) -> ReviewItem:
        """Create inbox item from pending pump prompt.

        Args:
            pump_data: Pump prompt data

        Returns:
            ReviewItem created from pump
        """
        pump_id = pump_data.get('pump_id', str(uuid.uuid4()))

        item = ReviewItem(
            item_type=ReviewItemType.PUMP,
            title=pump_data.get('intent', 'Pump Prompt'),
            description=pump_data.get('description', '')
                        or pump_data.get('payload', {}).get('description', '')
                        or f"From {pump_data.get('source_agent', 'unknown')}",
            urgency=UrgencyLevel(pump_data.get('urgency', 'normal')),
            source_agent=pump_data.get('source_agent', 'First Strike'),
            source_id=pump_id,
            payload=pump_data,
        )

        item.suggestions = self._generate_suggestions(item)
        self.items[item.item_id] = item
        self._save_items()

        return item

    async def ingest_action(self, action_data: dict) -> ReviewItem:
        """Create inbox item from pending governance action.

        Args:
            action_data: Governance action data

        Returns:
            ReviewItem created from action
        """
        action_id = action_data.get('action_id', str(uuid.uuid4()))

        item = ReviewItem(
            item_type=ReviewItemType.ACTION,
            title=action_data.get('title', 'Governance Action'),
            description=action_data.get('description', ''),
            urgency=UrgencyLevel(action_data.get('urgency', 'normal')),
            source_agent='Governance',
            source_id=action_id,
            payload=action_data,
        )

        item.suggestions = self._generate_suggestions(item)
        self.items[item.item_id] = item
        self._save_items()

        return item

    async def ingest_council(self, session_data: dict) -> ReviewItem:
        """Create inbox item from council session needing review.

        Args:
            session_data: Council session data

        Returns:
            ReviewItem created from council session
        """
        session_id = session_data.get('session_id', str(uuid.uuid4()))

        item = ReviewItem(
            item_type=ReviewItemType.COUNCIL,
            title=session_data.get('title', 'Council Session'),
            description=session_data.get('synthesis', '')
                        or f"Council: {session_data.get('type', 'unknown')}",
            urgency=UrgencyLevel(session_data.get('urgency', 'normal')),
            source_agent='Council',
            source_id=session_id,
            payload=session_data,
        )

        item.suggestions = self._generate_suggestions(item)
        self.items[item.item_id] = item
        self._save_items()

        return item

    async def refresh(self) -> List[ReviewItem]:
        """Pull latest items, deduplicate, generate suggestions.

        Returns:
            List of non-archived items
        """
        # Deduplicate by source_id
        seen_sources = {}
        for item in self.items.values():
            key = (item.item_type, item.source_id)
            if key not in seen_sources or item.created_at > seen_sources[key].created_at:
                seen_sources[key] = item

        self.items = {item.item_id: item for item in seen_sources.values()}

        # Regenerate suggestions for all items
        for item in self.items.values():
            item.suggestions = self._generate_suggestions(item)

        self._save_items()

        return self.get_items(archived=False)

    def get_items(
        self,
        type_filter: Optional[str] = None,
        urgency_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        archived: bool = False,
    ) -> List[ReviewItem]:
        """Get items from queue with optional filters.

        Args:
            type_filter: Filter by item type (PUMP, ACTION, COUNCIL, MANDATE)
            urgency_filter: Filter by urgency level
            tag_filter: Filter by tag
            archived: Include archived items

        Returns:
            List of matching items
        """
        source = self.archived if archived else self.items

        items = []
        for item in source.values():
            if type_filter and item.item_type != ReviewItemType(type_filter):
                continue
            if urgency_filter and item.urgency != UrgencyLevel(urgency_filter):
                continue
            if tag_filter and tag_filter not in item.tags:
                continue

            items.append(item)

        # Sort by urgency (critical first), then by creation time (newest first)
        urgency_order = {UrgencyLevel.CRITICAL: 0, UrgencyLevel.HIGH: 1,
                        UrgencyLevel.NORMAL: 2, UrgencyLevel.LOW: 3}
        items.sort(key=lambda x: (
            urgency_order.get(x.urgency, 4),
            x.created_at
        ), reverse=True)

        return items

    def get_item(self, item_id: str) -> Optional[ReviewItem]:
        """Get single item by ID.

        Args:
            item_id: Item ID

        Returns:
            ReviewItem or None if not found
        """
        return self.items.get(item_id) or self.archived.get(item_id)

    async def batch_tag(self, item_ids: List[str], tags: List[str]) -> List[ReviewItem]:
        """Tag multiple items.

        Args:
            item_ids: List of item IDs to tag
            tags: List of tags to apply

        Returns:
            List of tagged items
        """
        updated = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if not item:
                continue

            for tag in tags:
                if tag not in item.tags:
                    item.tags.append(tag)

            updated.append(item)

        self._save_items()
        return updated

    async def batch_link(self, item_ids: List[str]) -> List[ReviewItem]:
        """Link items to each other.

        Args:
            item_ids: List of item IDs to link

        Returns:
            List of linked items
        """
        if len(item_ids) < 2:
            return []

        # Create bidirectional links
        for item_id in item_ids:
            if item_id not in self.item_links:
                self.item_links[item_id] = []

            for other_id in item_ids:
                if other_id != item_id and other_id not in self.item_links[item_id]:
                    self.item_links[item_id].append(other_id)

        # Update items with linked_items
        updated = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item:
                item.linked_items = self.item_links.get(item_id, [])
                updated.append(item)

        self._save_items()
        self._save_links()

        return updated

    async def batch_archive(self, item_ids: List[str]) -> List[ReviewItem]:
        """Archive multiple items.

        Args:
            item_ids: List of item IDs to archive

        Returns:
            List of archived items
        """
        archived_items = []
        for item_id in item_ids:
            item = self.items.pop(item_id, None)
            if item:
                item.archived = True
                item.archived_at = datetime.utcnow().isoformat()
                self.archived[item_id] = item
                archived_items.append(item)

        self._save_items()
        self._save_archive()

        return archived_items

    async def batch_approve(self, item_ids: List[str]) -> List[Dict[str, Any]]:
        """Approve multiple items.

        NOTE: This is a tracking operation. Actual approval (dispatching to NCC)
        should be done via the pump/action approval endpoints.

        Args:
            item_ids: List of item IDs to approve

        Returns:
            List of approval results
        """
        results = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if not item:
                results.append({'item_id': item_id, 'success': False, 'error': 'Not found'})
                continue

            results.append({
                'item_id': item_id,
                'success': True,
                'item_type': item.item_type,
                'source_id': item.source_id,
                'timestamp': datetime.utcnow().isoformat()
            })

        return results

    async def batch_reject(self, item_ids: List[str], reason: str = '') -> List[Dict[str, Any]]:
        """Reject multiple items.

        Args:
            item_ids: List of item IDs to reject
            reason: Rejection reason

        Returns:
            List of rejection results
        """
        results = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if not item:
                results.append({'item_id': item_id, 'success': False, 'error': 'Not found'})
                continue

            results.append({
                'item_id': item_id,
                'success': True,
                'item_type': item.item_type,
                'source_id': item.source_id,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            })

        return results

    def _generate_suggestions(self, item: ReviewItem) -> List[Suggestion]:
        """Generate rule-based suggestions for an item.

        Deterministic, non-AI based suggestions based on item properties.

        Args:
            item: ReviewItem to generate suggestions for

        Returns:
            List of suggestions
        """
        suggestions = []

        # Critical urgency
        if item.urgency == UrgencyLevel.CRITICAL:
            suggestions.append(Suggestion(
                action_text='Review immediately',
                action_type='escalate',
                confidence=0.95,
                reasoning='Critical urgency detected - requires immediate attention'
            ))

        # PUMP-specific suggestions
        if item.item_type == ReviewItemType.PUMP:
            suggestions.append(Suggestion(
                action_text='Approve & dispatch to NCC',
                action_type='approve',
                confidence=0.75,
                reasoning='Approve pump prompt and dispatch to NCC for mandate execution'
            ))
            suggestions.append(Suggestion(
                action_text='Defer to next council',
                action_type='defer',
                confidence=0.6,
                reasoning='Defer pump to next council session for debate and synthesis'
            ))

        # ACTION-specific suggestions
        if item.item_type == ReviewItemType.ACTION:
            payload = item.payload or {}
            if payload.get('tier') == 'EXECUTE':
                suggestions.append(Suggestion(
                    action_text='Verify consent requirements',
                    action_type='escalate',
                    confidence=0.8,
                    reasoning='EXECUTE-tier action requires verification of consent before dispatch'
                ))

        # Old items (>24h)
        try:
            created = datetime.fromisoformat(item.created_at)
            now = datetime.utcnow()
            hours_old = (now - created).total_seconds() / 3600

            if hours_old > 24:
                suggestions.append(Suggestion(
                    action_text='Archive or escalate',
                    action_type='escalate',
                    confidence=0.7,
                    reasoning=f'Item is {int(hours_old)}h old - archive if stale or escalate if critical'
                ))
        except (ValueError, TypeError):
            pass

        return suggestions

    def get_stats(self) -> Dict[str, Any]:
        """Get review queue statistics.

        Returns:
            Dict of stats including counts by type, urgency, tags, etc.
        """
        items = list(self.items.values())
        archived_items = list(self.archived.values())

        type_counts = {}
        urgency_counts = {}
        tag_counts = {}

        for item in items:
            # Type counts
            item_type = item.item_type.value
            type_counts[item_type] = type_counts.get(item_type, 0) + 1

            # Urgency counts
            urg = item.urgency.value
            urgency_counts[urg] = urgency_counts.get(urg, 0) + 1

            # Tag counts
            for tag in item.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {
            'total_items': len(items),
            'archived_count': len(archived_items),
            'type_counts': type_counts,
            'urgency_counts': urgency_counts,
            'tag_counts': tag_counts,
            'critical_count': len([i for i in items if i.urgency == UrgencyLevel.CRITICAL]),
            'high_count': len([i for i in items if i.urgency == UrgencyLevel.HIGH]),
            'linked_pairs': sum(len(links) for links in self.item_links.values()) // 2,
        }
