"""Visible project/session navigation for the ordinary chat workspace."""
from __future__ import annotations

from nicegui import ui

from sovushka.state import api_get
from sovushka.uikit import action_button, panel, section_heading, text_field


class ChatProjectNavigation:
    def __init__(self, workspace, *, on_new, on_history, on_data=None):
        self.workspace = workspace
        self.on_new = on_new
        self.on_history = on_history
        self.on_data = on_data
        self.body = None
        self.sidebar = None
        self.owner_label = None
        self.title_label = None
        self.title_tooltip = None
        self.projects = []
        self.sessions = []
        self.mobile_open = False

    def render(self):
        with ui.element('aside').classes('sov-project-navigation') as self.sidebar:
            section_heading('Проекты и чаты')
            action_button('Новый чат', icon='add', variant='secondary',
                          classes='sov-project-nav-row', on_click=self.new_chat)
            self.body = ui.column().classes('sov-project-navigation-body')
            with ui.column().classes('sov-project-navigation-footer'):
                if self.on_data:
                    action_button('Данные', icon='o_database', variant='quiet',
                                  classes='sov-project-nav-row', on_click=self.open_data)
                action_button('История чатов', icon='o_history', variant='quiet',
                              classes='sov-project-nav-row', on_click=self.open_history)
                if self.workspace.is_admin:
                    action_button('Конфигурация', icon='o_settings', variant='quiet',
                                  classes='sov-project-nav-row',
                                  on_click=lambda: ui.navigate.to('/les/classic'))
                action_button('Закрыть список', icon='close', variant='quiet',
                              classes='sov-project-mobile-toggle', on_click=self.close)

    def render_heading(self):
        with ui.column().classes('sov-workspace-heading'):
            self.owner_label = ui.label('Без проекта').classes('sov-workspace-owner')
            self.title_label = ui.label('Новый чат').classes('sov-workspace-title')
            with self.title_label:
                self.title_tooltip = ui.tooltip('Новый чат')

    def toggle(self):
        self.mobile_open = not self.mobile_open
        self.sidebar.classes(add='sov-project-navigation--open' if self.mobile_open else '',
                             remove='' if self.mobile_open else 'sov-project-navigation--open')

    def close(self):
        self.mobile_open = False
        self.sidebar.classes(remove='sov-project-navigation--open')

    async def new_chat(self):
        await self.on_new()
        self.close()

    def open_history(self):
        self.close()
        return self.on_history()

    def open_data(self):
        self.close()
        return self.on_data()

    async def refresh(self):
        active = self.workspace.active
        pid = active.get('project_id')
        projects = await api_get('/api/projects')
        suffix = f'?project_id={pid}' if pid else ''
        sessions = await api_get(f'/api/workspace/sessions{suffix}')
        if self.owner_label:
            self.owner_label.set_text(self.workspace.project_names.get(pid, 'Проект') if pid else 'Без проекта')
            self.title_label.set_text(active.get('title') or 'Новый чат')
            self.title_tooltip.set_text(active.get('title') or 'Новый чат')
        self.body.clear()
        if projects is None or sessions is None:
            with self.body:
                ui.label('Не удалось загрузить проекты и чаты.').classes('sov-workspace-owner')
                action_button('Повторить', variant='quiet', on_click=self.refresh)
            return
        self.projects = projects.get('projects', []) if isinstance(projects, dict) else list(projects)
        self.sessions = sessions.get('sessions', []) if isinstance(sessions, dict) else list(sessions)
        self.workspace.project_names = {row['id']: row['name'] for row in self.projects}
        if self.owner_label and pid:
            self.owner_label.set_text(self.workspace.project_names.get(pid, 'Проект'))
        with self.body:
            self._project_row(None, 'Без проекта')
            if pid is None:
                self._session_rows()
            ui.label('Проекты').classes('sov-project-list-heading')
            for project in self.projects:
                if project.get('status') == 'archived':
                    continue
                self._project_row(project['id'], project['name'])
                if pid == project['id']:
                    self._session_rows()
            if self.workspace.is_admin:
                action_button('Создать проект', icon='add', variant='secondary',
                              classes='sov-project-nav-row', on_click=self.open_create)

    def _project_row(self, pid, title):
        selected = self.workspace.active.get('project_id') == pid
        async def choose():
            if await self.workspace.run(lambda: self.workspace.open_project(pid)):
                self.close()
        action_button(title, icon='o_folder_open' if pid else 'o_chat_bubble_outline',
                      variant='quiet', on_click=choose,
                      classes='sov-project-nav-row' + (' sov-project-nav-row--active' if selected else ''))

    def _session_rows(self):
        with ui.column().classes('sov-project-chat-list'):
            if not self.sessions:
                ui.label('Пока нет чатов').classes('sov-workspace-owner')
            for session in self.sessions:
                sid = session['session_id']
                async def choose(session_id=sid):
                    if await self.workspace.run(lambda: self.workspace.open_session(session_id)):
                        self.close()
                selected = self.workspace.active.get('session_id') == sid
                action_button(session.get('title') or session.get('first_question') or 'Новый чат',
                              icon='o_chat_bubble_outline', variant='quiet', on_click=choose,
                              classes='sov-project-nav-row' + (' sov-project-chat--active' if selected else '')).tooltip(
                                  session.get('title') or session.get('first_question') or 'Новый чат')

    def open_create(self):
        with ui.dialog() as dialog, panel(variant='raised', classes='sov-workspace-dialog'):
            section_heading('Создать проект', 'Объедините чаты, документы и память по одной задаче.')
            name = text_field(label='Название проекта', placeholder='Например, реконструкция школы', classes='w-full')
            async def save():
                if await self.workspace.run(lambda: self.workspace.create_project(name.value)):
                    dialog.close()
                    self.close()
            with ui.row().classes('w-full justify-end gap-2'):
                action_button('Отмена', variant='quiet', on_click=dialog.close)
                action_button('Создать проект', variant='primary', on_click=save)
        dialog.open()
