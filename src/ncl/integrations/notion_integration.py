# src/ncl/integrations/notion_integration.py
"""
Notion Integration
Single Source of Truth integration for NCL
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class NotionPage:
    """Represents a Notion page"""
    id: str
    title: str
    url: str
    last_edited: datetime
    properties: Dict[str, Any] = field(default_factory=dict)
    content: Optional[str] = None


@dataclass
class NotionDatabase:
    """Represents a Notion database"""
    id: str
    title: str
    url: str
    properties: Dict[str, Any] = field(default_factory=dict)


class NotionIntegration:
    """
    Notion Integration - Single Source of Truth

    Implements the PARA methodology and knowledge management
    system for the NCL doctrine implementation.
    """

    def __init__(self, api_token: Optional[str] = None, workspace_id: Optional[str] = None):
    """__init__ function/class."""

        self.logger = logging.getLogger(__name__)

        # Configuration
        self.api_token = api_token
        self.workspace_id = workspace_id
        self.api_base_url = "https://api.notion.com/v1"
        self.api_version = "2022-06-28"

        # State
        self.is_connected = False
        self.databases: Dict[str, NotionDatabase] = {}
        self.last_sync: Optional[datetime] = None

        # PARA structure
        self.para_structure = {
            'projects': None,  # Current projects database
            'areas': None,     # Areas of responsibility database
            'resources': None, # Resources database
            'archive': None    # Archive database
        }

    async def initialize(self) -> bool:
        """Initialize Notion integration"""
        try:
            self.logger.info("📝 Initializing Notion integration...")

            if not self.api_token:
                self.logger.warning("No Notion API token provided - running in mock mode")
                self.is_connected = True  # Mock connection
                return True

            # Test connection
            self.is_connected = await self._test_connection()

            if self.is_connected:
                # Discover databases
                await self._discover_databases()

                # Setup PARA structure
                await self._setup_para_structure()

            self.logger.info(f"✅ Notion integration initialized (connected: {self.is_connected})")
            return True

        except Exception as e:
            self.logger.error(f"❌ Notion integration failed: {e}")
            return False

    async def _test_connection(self) -> bool:
        """Test connection to Notion API"""
        # In real implementation, this would make an API call
        # For now, return True if token is provided
        return bool(self.api_token)

    async def _discover_databases(self):
        """Discover available Notion databases"""
        # Mock database discovery
        self.databases = {
            'projects_db': NotionDatabase(
                id='projects_db',
                title='Projects',
                url='https://notion.so/projects',
                properties={'type': 'database', 'structure': 'para_projects'}
            ),
            'areas_db': NotionDatabase(
                id='areas_db',
                title='Areas',
                url='https://notion.so/areas',
                properties={'type': 'database', 'structure': 'para_areas'}
            ),
            'resources_db': NotionDatabase(
                id='resources_db',
                title='Resources',
                url='https://notion.so/resources',
                properties={'type': 'database', 'structure': 'para_resources'}
            )
        }

    async def _setup_para_structure(self):
        """Setup PARA methodology structure"""
        # Map databases to PARA structure
        for db_id, database in self.databases.items():
            if 'projects' in database.title.lower():
                self.para_structure['projects'] = database
            elif 'areas' in database.title.lower():
                self.para_structure['areas'] = database
            elif 'resources' in database.title.lower():
                self.para_structure['resources'] = database

    async def create_page(self, database_id: str, title: str,
                         properties: Dict[str, Any] = None,
                         content: str = "") -> Optional[str]:
        """Create a new page in a database"""
        try:
            if not self.is_connected:
                return None

            # Mock page creation
            page_id = f"page_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            new_page = NotionPage(
                id=page_id,
                title=title,
                url=f"https://notion.so/{page_id}",
                last_edited=datetime.now(),
                properties=properties or {},
                content=content
            )

            self.logger.info(f"📄 Created Notion page: {title}")
            return page_id

        except Exception as e:
            self.logger.error(f"Failed to create page: {e}")
            return None

    async def update_page(self, page_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing page"""
        try:
            if not self.is_connected:
                return False

            # Mock page update
            self.logger.info(f"📝 Updated Notion page: {page_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to update page {page_id}: {e}")
            return False

    async def query_database(self, database_id: str,
                           filters: Dict[str, Any] = None) -> List[NotionPage]:
        """Query pages from a database"""
        try:
            if not self.is_connected:
                return []

            # Mock database query
            mock_pages = [
                NotionPage(
                    id=f"mock_page_{i}",
                    title=f"Mock Page {i}",
                    url=f"https://notion.so/mock_page_{i}",
                    last_edited=datetime.now() - timedelta(hours=i),
                    properties={'status': 'active', 'priority': 'high'},
                    content=f"Content for mock page {i}"
                )
                for i in range(1, 6)
            ]

            return mock_pages

        except Exception as e:
            self.logger.error(f"Failed to query database {database_id}: {e}")
            return []

    async def get_page_content(self, page_id: str) -> Optional[str]:
        """Get the content of a page"""
        try:
            if not self.is_connected:
                return None

            # Mock content retrieval
            return f"# Mock Page Content\n\nThis is the content for page {page_id}."

        except Exception as e:
            self.logger.error(f"Failed to get page content {page_id}: {e}")
            return None

    async def search_pages(self, query: str) -> List[NotionPage]:
        """Search for pages across the workspace"""
        try:
            if not self.is_connected:
                return []

            # Mock search results
            results = [
                NotionPage(
                    id=f"search_result_{i}",
                    title=f"Search Result {i} for '{query}'",
                    url=f"https://notion.so/search_result_{i}",
                    last_edited=datetime.now(),
                    properties={'relevance': 'high'},
                    content=f"Content matching search for '{query}'"
                )
                for i in range(1, 4)
            ]

            return results

        except Exception as e:
            self.logger.error(f"Search failed for query '{query}': {e}")
            return []

    async def sync_knowledge(self) -> Dict[str, Any]:
        """Sync knowledge from Notion to NCL systems"""
        try:
            sync_results = {
                'pages_synced': 0,
                'databases_updated': 0,
                'new_content': 0,
                'errors': 0
            }

            if not self.is_connected:
                return sync_results

            # Sync each PARA area
            for para_type, database in self.para_structure.items():
                if database:
                    try:
                        pages = await self.query_database(database.id)
                        sync_results['pages_synced'] += len(pages)
                        sync_results['databases_updated'] += 1
                    except Exception as e:
                        self.logger.error(f"Failed to sync {para_type}: {e}")
                        sync_results['errors'] += 1

            self.last_sync = datetime.now()
            return sync_results

        except Exception as e:
            self.logger.error(f"Knowledge sync failed: {e}")
            return {'errors': 1}

    async def create_doctrine_page(self, doctrine_section: str,
                                 content: str) -> Optional[str]:
        """Create a doctrine documentation page"""
        properties = {
            'Type': 'Doctrine',
            'Section': doctrine_section,
            'Status': 'Active',
            'Last Reviewed': datetime.now().date().isoformat()
        }

        return await self.create_page(
            database_id='resources_db',
            title=f"NCL Doctrine - {doctrine_section}",
            properties=properties,
            content=content
        )

    async def get_recent_changes(self, since: datetime) -> List[NotionPage]:
        """Get pages changed since a specific time"""
        try:
            if not self.is_connected:
                return []

            # Mock recent changes
            changes = [
                NotionPage(
                    id=f"recent_change_{i}",
                    title=f"Recent Change {i}",
                    url=f"https://notion.so/recent_change_{i}",
                    last_edited=datetime.now() - timedelta(minutes=i*10),
                    properties={'change_type': 'updated'}
                )
                for i in range(1, 6)
                if (datetime.now() - (datetime.now() - timedelta(minutes=i*10))) > since
            ]

            return changes

        except Exception as e:
            self.logger.error(f"Failed to get recent changes: {e}")
            return []

    async def get_connection_status(self) -> Dict[str, Any]:
        """Get integration connection status"""
        return {
            'connected': self.is_connected,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'databases_available': len(self.databases),
            'para_structure_complete': all(db is not None for db in self.para_structure.values()),
            'api_version': self.api_version
        }

    async def shutdown(self) -> bool:
        """Shutdown the Notion integration"""
        try:
            self.logger.info("🛑 Shutting down Notion integration")
            self.is_connected = False
            return True
        except Exception as e:
            self.logger.error(f"❌ Notion integration shutdown failed: {e}")
            return False
