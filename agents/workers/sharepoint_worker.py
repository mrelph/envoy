"""SharePoint worker — files, search, lists on SharePoint/OneDrive."""

import json
from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create(session_mgr=None):
    from agents import sharepoint_agent as sp

    @tool
    def sp_search(query: str, limit: int = 20) -> str:
        """Search SharePoint content across all sites using KQL.
        Args:
            query: Search keywords or KQL query
            limit: Max results (default 20)
        """
        return run(sp.search(query, limit))

    @tool
    def sp_files(operation: str = "list", library: str = "Documents", folder: str = "",
                 personal: bool = True, site_url: str = "") -> str:
        """Browse files and libraries on SharePoint/OneDrive.
        Args:
            operation: list (files), libraries (list libraries), sites (list sites)
            library: Document library name (default: Documents)
            folder: Subfolder path within library
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if operation == "sites":
            return run(sp.list_sites())
        if operation == "libraries":
            return run(sp.list_libraries(personal, site_url))
        return run(sp.list_files(library, folder, personal, site_url))

    @tool
    def sp_read(file_path: str, personal: bool = True, site_url: str = "") -> str:
        """Read a file from SharePoint/OneDrive. Handles .docx, .pptx, and text files.
        Binary files are downloaded and text-extracted automatically.
        Args:
            file_path: Server-relative URL of the file
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        return run(sp.read_file(file_path, personal=personal, site_url=site_url))

    @tool
    def sp_write(library: str, file_name: str, content: str = "", source_path: str = "",
                 folder: str = "", personal: bool = True, site_url: str = "") -> str:
        """Write or upload a file to SharePoint/OneDrive.
        For text content, provide content. For binary files (docx, pptx, etc.), provide source_path.
        Args:
            library: Document library name
            file_name: File name to create
            content: Text content to upload
            source_path: Local file path to upload (for binary files)
            folder: Subfolder path (created automatically)
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if source_path:
            return run(sp.upload_file(library, file_name, source_path, folder, personal, site_url))
        return run(sp.write_file(library, file_name, content, folder, personal, site_url))

    @tool
    def sp_manage(operation: str, path: str = "", library: str = "Documents",
                  folder_path: str = "", list_title: str = "", description: str = "",
                  item_id: int = 0, personal: bool = True, site_url: str = "") -> str:
        """File and list management — delete files, create folders, create/delete lists, delete list items.
        Args:
            operation: delete_file, create_folder, create_list, delete_list, delete_item
            path: Server-relative URL (for delete_file)
            library: Library name (for create_folder)
            folder_path: Folder path to create
            list_title: List name (for create_list, delete_list, delete_item)
            description: Description (for create_list)
            item_id: Item ID (for delete_item)
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        ops = {
            "delete_file": lambda: run(sp.delete_file(path, personal, site_url)),
            "create_folder": lambda: run(sp.create_folder(library, folder_path, personal, site_url)),
            "create_list": lambda: run(sp.create_list(list_title, description, personal, site_url)),
            "delete_list": lambda: run(sp.delete_list(list_title, personal, site_url)),
            "delete_item": lambda: run(sp.delete_item(list_title, item_id, personal, site_url)),
        }
        fn = ops.get(operation)
        return fn() if fn else f"Unknown operation: {operation}. Available: {list(ops.keys())}"

    @tool
    def sp_lists(operation: str = "browse", list_title: str = "", fields: str = "",
                 item_id: int = 0, filter_expr: str = "",
                 personal: bool = True, site_url: str = "") -> str:
        """Manage SharePoint lists — browse, read items, create/update items.
        Args:
            operation: browse (list all lists), items (get items), create (add item), update (update item)
            list_title: List name (required for items/create/update)
            fields: JSON string of field key-value pairs (for create/update)
            item_id: Item ID (for update)
            filter_expr: OData filter (for items, e.g. "Status eq 'Active'")
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if operation == "browse":
            return run(sp.list_lists(personal, site_url))
        if operation == "items":
            return run(sp.list_items(list_title, personal, site_url, filter_expr))
        if operation == "create":
            return run(sp.create_item(list_title, json.loads(fields), personal, site_url))
        if operation == "update":
            return run(sp.update_item(list_title, item_id, json.loads(fields), personal, site_url))
        return f"Unknown operation: {operation}"

    @tool
    def sp_analyze(file_path: str, instruction: str = "Summarize this document",
                   personal: bool = True, site_url: str = "") -> str:
        """Read a document from SharePoint/OneDrive and analyze it with a thinking model.
        Use this for summarization, extraction, or any deep analysis of document content.
        Handles .docx, .pptx, and text files. Uses a heavy-tier AI model.
        Args:
            file_path: Server-relative URL of the file
            instruction: What to do with the document (e.g. "Summarize", "Extract action items")
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        from agents.base import invoke_ai
        text = run(sp.read_file(file_path, personal=personal, site_url=site_url))
        if text.startswith("Error") or text.startswith("Could not") or text.startswith("Binary file"):
            return text
        prompt = f"""{instruction}

Document content:
{text}"""
        return invoke_ai(prompt, max_tokens=8000, tier="heavy")

    @tool
    def shared_context(operation: str = "read", key: str = "", value: str = "") -> str:
        """Read or post shared context visible to all workers.
        Args:
            operation: 'read' to get context, 'post' to share
            key: Context key
            value: Context value (for post)
        """
        from agents.workers import read_context, post_context
        if operation == "post" and key:
            post_context(key, value, source="sharepoint")
            return f"Posted to shared context: {key}"
        return read_context(key)

    return Agent(
        model=_model("medium"),
        system_prompt="You are a SharePoint/OneDrive specialist. You search content, browse and read files, upload documents, and manage SharePoint lists. When site_url is provided, target that team site; otherwise default to the user's personal OneDrive. For document summarization or analysis, ALWAYS use sp_analyze instead of sp_read. Use shared_context to post important findings for other workers.",
        tools=[sp_search, sp_files, sp_read, sp_write, sp_lists, sp_manage, sp_analyze, shared_context],
        callback_handler=None,
        **({"session_manager": session_mgr} if session_mgr else {}),
    )
