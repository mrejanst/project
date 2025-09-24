from odoo.addons.portal.controllers.portal import CustomerPortal, pager, get_error
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo.addons.website.controllers.main import Website
import math
import csv
import io
import base64
from datetime import datetime, timedelta
import json
import logging
from odoo import http, tools, _, SUPERUSER_ID, fields
from odoo.http import request, Response
import re
from html import unescape
import pytz

_logger = logging.getLogger(__name__)


def _get_user_timezone():
    """Get user timezone, default to Asia/Jakarta"""
    return 'Asia/Jakarta'


def _parse_datetime_to_utc(val):
    """Parse datetime-local format ke UTC untuk storage"""
    if not val:
        return False
    try:
        naive_dt = datetime.strptime(val, "%Y-%m-%dT%H:%M")
        wib_timezone = pytz.timezone('Asia/Jakarta')
        localized_dt = wib_timezone.localize(naive_dt)
        utc_dt = localized_dt.astimezone(pytz.utc)
        return utc_dt.replace(tzinfo=None)
    except Exception as e:
        _logger.warning("Error parsing datetime %s: %s", val, e)
        return False


def _format_datetime_to_user_tz(dt_val):
    """Convert UTC datetime dari database ke WIB untuk display"""
    if not dt_val:
        return ''
    try:
        if dt_val.tzinfo:
            utc_dt = dt_val
        else:
            utc_dt = pytz.utc.localize(dt_val)
        wib_timezone = pytz.timezone('Asia/Jakarta')
        local_dt = utc_dt.astimezone(wib_timezone)
        return local_dt.strftime('%Y-%m-%dT%H:%M')
    except Exception as e:
        _logger.warning("Error formatting datetime %s: %s", dt_val, e)
        return dt_val.strftime('%Y-%m-%dT%H:%M') if dt_val else ''


class PortalProjectControllers(http.Controller):
    def _get_task_with_subtasks(self, task):
        result = [task]
        for child in task.child_ids:
            result.extend(self._get_task_with_subtasks(child))
        return result

    def _get_status_label(self, status_value):
        status_mapping = {
            'new': 'New',
            'in_progress': 'In Progress',
            'done': 'Finished',
            'cancel': 'Cancelled'
        }
        if not status_value or not isinstance(status_value, str):
            return 'Undefined'
        return status_mapping.get(status_value, status_value.replace('_', ' ').title())

    def _get_task_buttons_visibility(self, task):
        return {
            'start_stop_timer': True,
            'start_progress': task.z_project_task_state == 'new',
            'finish_task': task.z_project_task_state == 'in_progress',
            'cancel': task.z_project_task_state not in ['done', 'cancel'],
            'set_to_draft': task.z_project_task_state in ['cancel', 'done']
        }

    def _get_hierarchical_tasks(self, tasks):
        if not tasks:
            return []
        parent_tasks = tasks.filtered(lambda t: not t.parent_id)
        hierarchical_tasks = []
        for parent in parent_tasks:
            hierarchical_tasks.append(parent)
            children = tasks.filtered(lambda t: t.parent_id.id == parent.id)
            hierarchical_tasks.extend(children)
        return hierarchical_tasks

    def _get_common_template_data(self):
        return {
            'technologies': request.env['technology.used'].sudo().search([]),
            'severities': request.env['severity.master'].sudo().search([]),
            'regionals': request.env['area.regional'].sudo().search([]),
            'master_tasks': request.env['task.master'].sudo().search([]),
            'employees': request.env['hr.employee'].sudo().search([]),
        }

    def _get_group_display_name(self, groupby, key):
        if not key:
            return 'undefined', 'Undefined'
        try:
            Task = request.env['project.task'].sudo()
            group_field = Task._fields.get(groupby)
            if hasattr(group_field, 'comodel_name') and group_field.comodel_name:
                rec = request.env[group_field.comodel_name].sudo().browse(key)
                if rec and rec.exists():
                    group_value_id = str(rec.id)
                    if hasattr(rec, 'z_name') and rec.z_name:
                        group_value_name = rec.z_name
                    elif hasattr(rec, 'name') and rec.name:
                        group_value_name = rec.name
                    else:
                        group_value_name = rec.display_name or str(key)
                    return group_value_id, group_value_name
            return str(key), str(key)
        except Exception as e:
            _logger.warning(f"Error resolving group value for {groupby}={key}: {e}")
            return str(key) if key else 'undefined', str(key) if key else 'Undefined'

    @http.route([
        '/portal/tasks',
        '/portal/tasks/page/<int:page>',
        '/portal/tasks/delete/<int:task_id>',
        '/portal/task/<int:task_id>',
        '/portal/tasks/parent/<int:parent_id>',
        '/portal/tasks/parent/<int:parent_id>/page/<int:page>',
        '/portal/tasks/parent/<int:parent_id>/new',
    ], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_tasks_consolidated(self, task_id=None, page=1, search='', sortby='name', groupby='', parent_id=None,
                                  project_id=None, **kw):
        Task = request.env['project.task'].sudo()
        step = 20
        searchbar_sortings = {
            'name': {'label': 'Task Name', 'order': 'name'},
            'project': {'label': 'Project', 'order': 'project_id'},
            'customer': {'label': 'Customer', 'order': 'partner_id'},
            'status': {'label': 'Status', 'order': 'z_project_task_state'},
        }
        searchbar_groupings = {
            '': {'label': 'None'},
            'z_master_task_id': {'label': 'Name of Task'},
            'project_id': {'label': 'Project'},
            'partner_id': {'label': 'Customer'},
            'z_project_task_state': {'label': 'Status'},
            'z_technology_id': {'label': 'Technology'},
            'z_severity_id': {'label': 'Severity'},
        }
        common_data = self._get_common_template_data()
        if not project_id and kw.get('project_id'):
            try:
                project_id = int(kw.get('project_id'))
            except (ValueError, TypeError):
                project_id = None
        if not parent_id and kw.get('parent_id'):
            try:
                parent_id = int(kw.get('parent_id'))
            except (ValueError, TypeError):
                parent_id = None

        parent_task = None
        project = None
        if parent_id:
            parent_task = Task.browse(parent_id)
            if not parent_task or not parent_task.exists():
                parent_task = Task.search([('id', '=', parent_id)], limit=1)
                if not parent_task or not parent_task.exists():
                    _logger.warning(f"Parent task dengan ID {parent_id} tidak ditemukan.")
                    return request.redirect('/portal/tasks?error=Parent task not found')

        if project_id:
            project = request.env['project.project'].sudo().browse(project_id).exists()

        # DELETE
        if request.httprequest.method == 'POST' and task_id and '/delete/' in request.httprequest.path:
            task = Task.browse(task_id).exists()
            if task:
                task.unlink()
            redirect_url = f'/portal/tasks/parent/{parent_id}' if parent_id else '/portal/tasks'
            return request.redirect(f'{redirect_url}?success=Task deleted successfully')

        # ACTION buttons
        if request.httprequest.method == 'POST' and task_id and kw.get('function'):
            task = Task.browse(task_id).exists()
            if not task:
                return request.redirect(f'/portal/task/{task_id}?mode=edit&error=Task not found')
            function = kw.get('function')
            try:
                if function == 'start_progress':
                    task.z_project_task_state = 'in_progress'
                elif function == 'finish_task':
                    task.z_project_task_state = 'done'
                elif function == 'cancel':
                    task.z_project_task_state = 'cancel'
                elif function == 'set_to_draft':
                    task.z_project_task_state = 'new'
                return request.redirect(f'/portal/task/{task.id}?mode=edit&success=Action completed successfully')
            except Exception as e:
                _logger.error("Error in task action: %s", str(e))
                return request.redirect(f'/portal/task/{task.id}?mode=edit&error={tools.html_escape(str(e))}')

        # CREATE task/subtask (TIDAK BOLEH di-nested dalam except!)
        if request.httprequest.method == 'POST' and not task_id and '/delete/' not in request.httprequest.path:
            try:
                head_ids = request.httprequest.form.getlist('z_head_assignes_ids')
                member_ids = request.httprequest.form.getlist('z_member_assignes_ids')

                def safe_float(val):
                    try:
                        return float(val) if val and str(val).strip() else 0.0
                    except (ValueError, TypeError):
                        return 0.0

                def safe_int(val):
                    try:
                        return int(val) if val and str(val).strip() else False
                    except (ValueError, TypeError):
                        return False

                task_data = {
                    'name': kw.get('name') or 'New Task',
                    'description': self._process_description(kw.get('description', '')),
                    'z_project_task_state': kw.get('z_project_task_state', 'new'),
                    'z_master_task_id': safe_int(kw.get('z_master_task_id')),
                    'z_bobot': safe_float(kw.get('z_bobot')),
                    'z_technology_id': safe_int(kw.get('z_technology_id')),
                    'z_severity_id': safe_int(kw.get('z_severity_id')),
                    'z_mandays_budget': safe_float(kw.get('z_mandays_budget')),
                    'z_actual_budget_mandays': safe_float(kw.get('z_actual_budget_mandays')),
                    'z_progress_project': safe_float(kw.get('z_progress_project')),
                    'z_quality_entry': safe_float(kw.get('z_quality_entry')),
                    'z_planned_start_date': kw.get('z_planned_start_date') or False,
                    'z_planned_end_date': kw.get('z_planned_end_date') or False,
                }
                # Assignees default kosong saat create baru
                if head_ids and not parent_id:
                    task_data['z_head_assignes_ids'] = [(6, 0, [int(h) for h in head_ids if h])]
                if member_ids and not parent_id:
                    task_data['z_member_assignes_ids'] = [(6, 0, [int(m) for m in member_ids if m])]
                if parent_id:
                    parent_task_obj = Task.browse(parent_id).exists()
                    if parent_task_obj:
                        task_data.update({
                            'parent_id': parent_task_obj.id,
                            'project_id': parent_task_obj.project_id.id if parent_task_obj.project_id else False,
                            'partner_id': parent_task_obj.partner_id.id if parent_task_obj.partner_id else False,
                            'z_name_of_project': parent_task_obj.z_name_of_project or '',
                        })
                    if not parent_task_obj:
                        _logger.error(f"Failed to create subtask: Parent task with ID {parent_id} not found.")
                        return request.redirect('/portal/tasks?error=Cannot create subtask, parent task not found.')
                    existing_subtasks = Task.search([('parent_id', '=', parent_task_obj.id)])
                    subtask_number = len(existing_subtasks) + 1
                    task_data.update({
                        'parent_id': parent_task_obj.id,
                        'project_id': parent_task_obj.project_id.id if parent_task_obj.project_id else False,
                        'partner_id': parent_task_obj.partner_id.id if parent_task_obj.partner_id else False,
                        'name': f"{parent_task_obj.name}.{str(subtask_number).zfill(2)}",
                        'z_name_of_project': parent_task_obj.z_name_of_project or '',
                    })
                    if not task_data['z_technology_id'] and parent_task_obj.z_technology_id:
                        task_data['z_technology_id'] = parent_task_obj.z_technology_id.id
                    if not task_data['z_severity_id'] and parent_task_obj.z_severity_id:
                        task_data['z_severity_id'] = parent_task_obj.z_severity_id.id
                    task = Task.create(task_data)
                    return request.redirect(
                        f'/portal/task/{task.id}?mode=edit&success=Subtask created successfully')
                else:
                    project_id_from_form = safe_int(kw.get('project_id'))
                    if project_id_from_form:
                        target_project_id = project_id_from_form
                    elif project_id:
                        target_project_id = project_id
                    else:
                        target_project_id = None
                    if target_project_id:
                        project_obj = request.env['project.project'].sudo().browse(target_project_id)
                        if project_obj.exists():
                            task_data['project_id'] = project_obj.id
                            task_data['partner_id'] = project_obj.partner_id.id if project_obj.partner_id else False
                            task_data['z_name_of_project'] = project_obj.name
                            if not kw.get('name') or kw.get('name') == 'New Task':
                                master_task_name = ""
                                if task_data['z_master_task_id']:
                                    master_task = request.env['task.master'].sudo().browse(
                                        task_data['z_master_task_id'])
                                    if master_task.exists():
                                        master_task_name = master_task.z_name
                                if master_task_name:
                                    task_data['name'] = f"{project_obj.name} - {master_task_name}"
                                else:
                                    task_data['name'] = f"Task for {project_obj.name}"
                    task = Task.create(task_data)
                    return request.redirect(f'/portal/task/{task.id}?mode=edit&success=Task created successfully')
            except Exception as e:
                _logger.error("Error creating task: %s", str(e))
                redirect_url = f'/portal/tasks/parent/{parent_id}' if parent_id else '/portal/tasks'
                return request.redirect(f'{redirect_url}?mode=new&error=' + tools.html_escape(str(e)))
        # PATCH: Timer pause/resume logic fix
        if request.httprequest.path.endswith('/timer'):
            if request.httprequest.method == 'POST':
                try:
                    task = Task.browse(task_id).exists()
                    if not task:
                        return Response(json.dumps({'success': False, 'error': 'Task not found'}),
                                        content_type='application/json')
                    action = request.httprequest.form.get('action')
                    employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)],
                                                                        limit=1)
                    if not employee:
                        return Response(json.dumps({'success': False, 'error': 'Employee not found'}),
                                        content_type='application/json')
                    # Timer start/resume update status to in_progress
                    if action in ['start', 'resume']:
                        if task.z_project_task_state == 'new':
                            task.z_project_task_state = 'in_progress'
                    if action == 'start':
                        open_line = request.env['account.analytic.line'].sudo().search([
                            ('task_id', '=', task.id),
                            ('employee_id', '=', employee.id),
                            ('z_timesheet_end_date', '=', False),
                        ], limit=1)
                        if open_line:
                            if hasattr(open_line, 'z_is_paused') and open_line.z_is_paused:
                                open_line.z_is_paused = False
                                start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                                return Response(json.dumps({
                                    'success': True,
                                    'start_at': start_at,
                                    'message': 'Timer resumed',
                                    'action': 'resumed'
                                }), content_type='application/json')
                            else:
                                start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                                return Response(json.dumps({
                                    'success': True,
                                    'start_at': start_at,
                                    'message': 'Timer already running',
                                    'action': 'already_running'
                                }), content_type='application/json')
                        now_utc = fields.Datetime.now()
                        line_vals = {
                            'task_id': task.id,
                            'project_id': task.project_id.id if task.project_id else False,
                            'employee_id': employee.id,
                            'name': f'Timer started for {task.name}',
                            'z_timesheet_start_date': now_utc,
                            'date': fields.Date.context_today(request.env.user),
                        }
                        if hasattr(request.env['account.analytic.line'], 'z_is_paused'):
                            line_vals['z_is_paused'] = False
                        # Add pause/resume history
                        if hasattr(request.env['account.analytic.line'], 'z_pause_resume_list'):
                            line_vals['z_pause_resume_list'] = []
                        new_line = request.env['account.analytic.line'].sudo().create(line_vals)
                        start_at = fields.Datetime.to_string(now_utc)
                        return Response(json.dumps({
                            'success': True,
                            'start_at': start_at,
                            'message': 'Timer started',
                            'action': 'started',
                            'timesheet_id': new_line.id
                        }), content_type='application/json')
                    elif action == 'pause':
                        open_line = request.env['account.analytic.line'].sudo().search([
                            ('task_id', '=', task.id),
                            ('employee_id', '=', employee.id),
                            ('z_timesheet_end_date', '=', False),
                        ], order='id desc', limit=1)
                        if not open_line:
                            return Response(json.dumps({'success': False, 'error': 'No running timer found'}),
                                            content_type='application/json')
                        if hasattr(open_line, 'z_is_paused'):
                            open_line.z_is_paused = True
                            now_utc = fields.Datetime.now()
                            duration = (now_utc - open_line.z_timesheet_start_date).total_seconds() / 3600
                            pause_list = getattr(open_line, 'z_pause_resume_list', [])
                            pause_list.append({'pause_at': now_utc})
                            if hasattr(open_line, 'z_pause_resume_list'):
                                open_line.z_pause_resume_list = pause_list
                            if hasattr(open_line, 'z_accumulated_time'):
                                open_line.z_accumulated_time = duration
                            else:
                                open_line.unit_amount = round(duration, 2)
                        return Response(json.dumps({
                            'success': True,
                            'message': 'Timer paused',
                            'action': 'paused'
                        }), content_type='application/json')
                    elif action == 'resume':
                        open_line = request.env['account.analytic.line'].sudo().search([
                            ('task_id', '=', task.id),
                            ('employee_id', '=', employee.id),
                            ('z_timesheet_end_date', '=', False),
                        ], order='id desc', limit=1)
                        if not open_line:
                            return Response(json.dumps({'success': False, 'error': 'No paused timer found'}),
                                            content_type='application/json')
                        if hasattr(open_line, 'z_is_paused'):
                            open_line.z_is_paused = False
                            pause_list = getattr(open_line, 'z_pause_resume_list', [])
                            pause_list.append({'resume_at': fields.Datetime.now()})
                            if hasattr(open_line, 'z_pause_resume_list'):
                                open_line.z_pause_resume_list = pause_list
                        start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                        return Response(json.dumps({
                            'success': True,
                            'start_at': start_at,
                            'message': 'Timer resumed',
                            'action': 'resumed'
                        }), content_type='application/json')
                    elif action == 'stop':
                        desc = request.httprequest.form.get('description', '').strip()
                        if not desc:
                            return Response(
                                json.dumps({'success': False, 'error': 'Description is required when stopping timer'}),
                                content_type='application/json')
                        open_line = request.env['account.analytic.line'].sudo().search([
                            ('task_id', '=', task.id),
                            ('employee_id', '=', employee.id),
                            ('z_timesheet_end_date', '=', False),
                        ], order='id desc', limit=1)
                        if not open_line:
                            return Response(json.dumps({'success': False, 'error': 'No running timer found'}),
                                            content_type='application/json')
                        end_time_utc = fields.Datetime.now()
                        start_time = open_line.z_timesheet_start_date
                        duration = 0
                        if start_time and end_time_utc:
                            pause_list = getattr(open_line, 'z_pause_resume_list', [])
                            if pause_list:
                                last_resume = start_time
                                total_active = 0
                                for entry in pause_list:
                                    pause_at = entry.get('pause_at')
                                    resume_at = entry.get('resume_at')
                                    if pause_at and last_resume:
                                        total_active += (pause_at - last_resume).total_seconds()
                                    if resume_at:
                                        last_resume = resume_at
                                if last_resume:
                                    total_active += (end_time_utc - last_resume).total_seconds()
                                duration = total_active / 3600
                            else:
                                duration = (end_time_utc - start_time).total_seconds() / 3600
                            if hasattr(open_line, 'z_accumulated_time') and open_line.z_accumulated_time:
                                duration = open_line.z_accumulated_time
                            open_line.unit_amount = round(duration, 2)
                        update_vals = {
                            'z_timesheet_end_date': end_time_utc,
                            'name': desc,
                        }
                        if hasattr(open_line, 'z_is_paused'):
                            update_vals['z_is_paused'] = False
                        if hasattr(open_line, 'z_pause_resume_list'):
                            update_vals['z_pause_resume_list'] = getattr(open_line, 'z_pause_resume_list', [])
                        open_line.write(update_vals)
                        attachment_ids = []
                        if hasattr(request, 'httprequest') and request.httprequest.files:
                            files = request.httprequest.files
                            for file_key in files:
                                if file_key == 'attachments':
                                    file_list = files.getlist(file_key)
                                    for uploaded_file in file_list:
                                        if uploaded_file and uploaded_file.filename:
                                            try:
                                                file_content = uploaded_file.read()
                                                attachment = request.env['ir.attachment'].sudo().create({
                                                    'name': uploaded_file.filename,
                                                    'type': 'binary',
                                                    'datas': base64.b64encode(file_content),
                                                    'res_model': 'account.analytic.line',
                                                    'res_id': open_line.id,
                                                    'mimetype': uploaded_file.content_type or 'application/octet-stream',
                                                    'description': f'Timer attachment for timesheet {open_line.id}',
                                                    'public': False,
                                                })
                                                attachment_ids.append(attachment.id)
                                            except Exception as e:
                                                _logger.error("Error uploading attachment: %s", str(e))
                        if attachment_ids:
                            open_line.message_post(
                                body=f"Timer stopped with {len(attachment_ids)} attachment(s)",
                                attachment_ids=attachment_ids
                            )
                        return Response(json.dumps({
                            'success': True,
                            'attachments_count': len(attachment_ids),
                            'timesheet_id': open_line.id,
                            'duration': round(duration, 2),
                            'action': 'stopped'
                        }), content_type='application/json')
                    else:
                        return Response(json.dumps({'success': False, 'error': 'Invalid action'}),
                                        content_type='application/json')
                except Exception as e:
                    _logger.error('Timer error: %s', e)
                    return Response(json.dumps({'success': False, 'error': str(e)}),
                                    content_type='application/json')

        # EDIT VIEW
        if task_id and '/task/' in request.httprequest.path:
            task = Task.browse(task_id).exists()
            if not task:
                redirect_url = f'/portal/tasks/parent/{parent_id}' if parent_id else '/portal/tasks'
                return request.redirect(f'{redirect_url}?error=Task not found')

            task_description = self._convert_html_to_text(task.description or '')
            status_label = self._get_status_label(task.z_project_task_state)
            button_visibility = self._get_task_buttons_visibility(task)

            employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
            active_timer_start = ''
            active_timer_running = False
            active_timer_paused = False
            master = task.z_master_task_id.z_name if task.z_master_task_id else ''

            if employee:
                open_line = request.env['account.analytic.line'].sudo().search([
                    ('task_id', '=', task.id),
                    ('employee_id', '=', employee.id),
                    ('z_timesheet_end_date', '=', False),
                ], order='id desc', limit=1)
                if open_line and open_line.z_timesheet_start_date:
                    active_timer_start = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                    active_timer_running = True
                    # FIXED: Check for pause state if field exists
                    if hasattr(open_line, 'z_is_paused'):
                        active_timer_paused = open_line.z_is_paused

            subtasks = Task.search([('parent_id', '=', task.id)])

            values = {
                'page_name': 'Edit Task',
                'task': task,
                'master': master,
                'button_visibility': button_visibility,
                'status_label': status_label,
                'task_description': task_description,
                'task_description_html': task.description or '',
                'timesheets': task.timesheet_ids,
                'subtasks': subtasks,
                'kw': {'mode': 'edit'},
                'searchbar_sortings': searchbar_sortings,
                'searchbar_groupings': searchbar_groupings,
                'sortby': sortby,
                'groupby': groupby,
                'search': search,
                'parent_id': parent_id,
                'project_id': project_id,
                'project': project,
                'active_timer_start': active_timer_start,
                'active_timer_running': active_timer_running,
                'active_timer_paused': active_timer_paused,
                **common_data
            }
            return request.render('z_project.portal_task_page', values)

        # NEW mode
        if kw.get('mode') == 'new':
            parent_data = {}

            # FIXED: Enhanced parent data handling
            if parent_id:
                parent_task_obj = Task.browse(parent_id).exists()
                if parent_task_obj:
                    parent_data = {
                        'parent_task': parent_task_obj,
                        'project_id': parent_task_obj.project_id.id if parent_task_obj.project_id else False,
                        'project_name': parent_task_obj.project_id.name if parent_task_obj.project_id else '',
                        'customer_id': parent_task_obj.partner_id.id if parent_task_obj.partner_id else False,
                        'customer_name': parent_task_obj.partner_id.name if parent_task_obj.partner_id else '',
                        'z_name_of_project': parent_task_obj.z_name_of_project or '',
                        'z_technology_id': parent_task_obj.z_technology_id.id if parent_task_obj.z_technology_id else False,
                        'z_severity_id': parent_task_obj.z_severity_id.id if parent_task_obj.z_severity_id else False,
                        'z_head_assignes_ids': parent_task_obj.z_head_assignes_ids.ids,
                        'z_member_assignes_ids': parent_task_obj.z_member_assignes_ids.ids,
                    }
            elif project_id:
                # FIXED: Project data for new parent task
                project_obj = request.env['project.project'].sudo().browse(project_id).exists()
                if project_obj:
                    parent_data = {
                        'project_id': project_obj.id,
                        'project_name': project_obj.name,
                        'customer_id': project_obj.partner_id.id if project_obj.partner_id else False,
                        'customer_name': project_obj.partner_id.name if project_obj.partner_id else '',
                        'z_name_of_project': project_obj.name,
                    }

            values = {
                'page_name': 'New Subtask' if parent_id else 'New Task',
                'kw': kw,
                'parent_id': parent_id,
                'project_id': project_id,
                'project': project,
                'task': False,
                'timesheets': False,
                'subtasks': False,
                'active_timer_start': '',
                'active_timer_running': False,
                'active_timer_paused': False,
                **parent_data,
                **common_data
            }
            return request.render('z_project.portal_task_page', values)

        # LIST VIEW (same as before but with project context)
        domain = []
        if search:
            domain += [
                '|', '|', '|',
                ('name', 'ilike', search),
                ('project_id.name', 'ilike', search),
                ('partner_id.name', 'ilike', search),
                ('z_master_task_id.z_name', 'ilike', search),
            ]
        if parent_id:
            domain.append(('parent_id', '=', parent_id))
        if project_id:
            domain.append(('project_id', '=', project_id))

        url = '/portal/tasks' if not parent_id else f'/portal/tasks/parent/{parent_id}'
        sort_field = searchbar_sortings.get(sortby, {}).get('order', 'name')

        if groupby:
            group_field_name = groupby
            data_groups = Task.read_group(
                domain,
                fields=[group_field_name],
                groupby=[group_field_name],
                orderby=group_field_name,
                limit=None
            )

            group_keys = []
            for group in data_groups:
                gv = group.get(group_field_name)
                if gv:
                    if isinstance(gv, (list, tuple)) and len(gv) > 0:
                        group_keys.append(gv[0])
                    else:
                        group_keys.append(gv)
                else:
                    group_keys.append(False)

            def sort_group_key(key):
                if key is False:
                    return (1, 'Undefined')
                else:
                    _, display_name = self._get_group_display_name(groupby, key)
                    return (0, display_name)

            group_keys.sort(key=sort_group_key)
            total_groups = len(group_keys)

            pager_details = pager(
                url=url, total=total_groups, page=page, step=step, scope=3,
                url_args={'search': search, 'sortby': sortby, 'groupby': groupby, 'parent_id': parent_id,
                          'project_id': project_id}
            )

            group_keys_on_page = group_keys[pager_details['offset']:pager_details['offset'] + step]
            data_task_on_group = []

            for key in group_keys_on_page:
                group_domain = list(domain)
                if key:
                    group_domain.append((groupby, '=', key))
                else:
                    group_domain.append((groupby, '=', False))

                group_tasks = Task.search(group_domain, order=sort_field)
                hierarchical_tasks = self._get_hierarchical_tasks(group_tasks)

                group_value_id, group_value_name = self._get_group_display_name(groupby, key)

                data_task_on_group.append({
                    'group_value': None,
                    'group_value_id': group_value_id,
                    'group_value_name': group_value_name,
                    'group_key': key,
                    'tasks': hierarchical_tasks,
                })

            tasks = data_task_on_group
            pager_details_out = pager_details

        else:
            # Flat view
            total = Task.search_count(domain)
            pager_details_out = pager(
                url=url, total=total, page=page, step=step, scope=3,
                url_args={'search': search, 'sortby': sortby, 'groupby': groupby, 'parent_id': parent_id,
                          'project_id': project_id}
            )
            tasks = Task.search(domain, offset=pager_details_out['offset'], limit=step, order=sort_field)

        page_name = 'Tasks'
        if parent_id and parent_task:
            page_name = f'Subtasks of {parent_task.name}'
        elif parent_id:
            page_name = 'Subtasks (Parent not found)'
        elif project_id and project:
            page_name = f'Tasks for {project.name}'

        values = {
            'page_name': page_name,
            'tasks': tasks,
            'pager_header': pager_details_out,
            'search': search,
            'sortby': sortby,
            'groupby': groupby,
            'searchbar_sortings': searchbar_sortings,
            'searchbar_groupings': searchbar_groupings,
            'kw': kw,
            'parent_id': parent_id,
            'parent_task': parent_task,
            'project_id': project_id,
            'project': project,
            'task': False,
            'timesheets': False,
            'subtasks': False,
            'active_timer_start': '',
            'active_timer_running': False,
            'active_timer_paused': False,
            **common_data
        }
        return request.render('z_project.portal_task_page', values)

    def _process_description(self, description):
        """Process description text to HTML"""
        if not description:
            return False
        return description.replace('\r\n', '\n').replace('\n', '<br/>')

    def _convert_html_to_text(self, html_content):
        """Convert HTML description to plain text"""
        if not html_content:
            return ''
        desc = re.sub(r'<br\s*/?>', '\n', html_content)
        desc = re.sub(r'</p\s*>', '\n', desc)
        desc = re.sub(r'<[^>]+>', '', desc)
        desc = unescape(desc)
        return "\n".join([line.rstrip() for line in desc.splitlines()]).strip()

    # FIXED: Enhanced timer with PAUSE/RESUME functionality
    @http.route('/portal/task/<int:task_id>/timer', type='http', auth='user', website=True, methods=['POST'])
    def portal_task_timer(self, task_id, **post):
        try:
            task = request.env['project.task'].sudo().browse(task_id).exists()
            if not task:
                return Response(json.dumps({'success': False, 'error': 'Task not found'}),
                                content_type='application/json')

            action = post.get('action')
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

            if not employee:
                return Response(json.dumps({'success': False, 'error': 'Employee not found'}),
                                content_type='application/json')

            if action == 'start':
                # Check if there's already a running timer
                open_line = request.env['account.analytic.line'].sudo().search([
                    ('task_id', '=', task.id),
                    ('employee_id', '=', employee.id),
                    ('z_timesheet_end_date', '=', False),
                ], limit=1)

                if open_line:
                    # If timer exists but is paused, resume it
                    if hasattr(open_line, 'z_is_paused') and open_line.z_is_paused:
                        open_line.z_is_paused = False
                        start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                        return Response(json.dumps({
                            'success': True,
                            'start_at': start_at,
                            'message': 'Timer resumed',
                            'action': 'resumed'
                        }), content_type='application/json')
                    else:
                        # Timer already running
                        start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                        return Response(json.dumps({
                            'success': True,
                            'start_at': start_at,
                            'message': 'Timer already running',
                            'action': 'already_running'
                        }), content_type='application/json')

                # Create new timer
                now_utc = fields.Datetime.now()
                line_vals = {
                    'task_id': task.id,
                    'project_id': task.project_id.id if task.project_id else False,
                    'employee_id': employee.id,
                    'name': f'Timer started for {task.name}',
                    'z_timesheet_start_date': now_utc,
                    'date': fields.Date.context_today(request.env.user),
                }

                if hasattr(request.env['account.analytic.line'], 'z_is_paused'):
                    line_vals['z_is_paused'] = False

                new_line = request.env['account.analytic.line'].sudo().create(line_vals)
                start_at = fields.Datetime.to_string(now_utc)
                return Response(json.dumps({
                    'success': True,
                    'start_at': start_at,
                    'message': 'Timer started',
                    'action': 'started',
                    'timesheet_id': new_line.id
                }), content_type='application/json')

            elif action == 'pause':
                # FIXED: PAUSE functionality
                open_line = request.env['account.analytic.line'].sudo().search([
                    ('task_id', '=', task.id),
                    ('employee_id', '=', employee.id),
                    ('z_timesheet_end_date', '=', False),
                ], order='id desc', limit=1)

                if not open_line:
                    return Response(json.dumps({'success': False, 'error': 'No running timer found'}),
                                    content_type='application/json')

                # Mark as paused if field exists
                if hasattr(open_line, 'z_is_paused'):
                    open_line.z_is_paused = True

                    # Calculate and store accumulated time so far
                    if open_line.z_timesheet_start_date:
                        now_utc = fields.Datetime.now()
                        duration = (now_utc - open_line.z_timesheet_start_date).total_seconds() / 3600

                        # Store accumulated time in a custom field if it exists
                        if hasattr(open_line, 'z_accumulated_time'):
                            open_line.z_accumulated_time = duration
                        else:
                            open_line.unit_amount = round(duration, 2)

                return Response(json.dumps({
                    'success': True,
                    'message': 'Timer paused',
                    'action': 'paused'
                }), content_type='application/json')

            elif action == 'resume':
                # FIXED: RESUME functionality
                open_line = request.env['account.analytic.line'].sudo().search([
                    ('task_id', '=', task.id),
                    ('employee_id', '=', employee.id),
                    ('z_timesheet_end_date', '=', False),
                ], order='id desc', limit=1)

                if not open_line:
                    return Response(json.dumps({'success': False, 'error': 'No paused timer found'}),
                                    content_type='application/json')

                # Resume the timer
                if hasattr(open_line, 'z_is_paused'):
                    open_line.z_is_paused = False

                start_at = fields.Datetime.to_string(open_line.z_timesheet_start_date)
                return Response(json.dumps({
                    'success': True,
                    'start_at': start_at,
                    'message': 'Timer resumed',
                    'action': 'resumed'
                }), content_type='application/json')

            elif action == 'stop':
                desc = post.get('description', '').strip()

                if not desc:
                    return Response(
                        json.dumps({'success': False, 'error': 'Description is required when stopping timer'}),
                        content_type='application/json')

                open_line = request.env['account.analytic.line'].sudo().search([
                    ('task_id', '=', task.id),
                    ('employee_id', '=', employee.id),
                    ('z_timesheet_end_date', '=', False),
                ], order='id desc', limit=1)

                if not open_line:
                    return Response(json.dumps({'success': False, 'error': 'No running timer found'}),
                                    content_type='application/json')

                end_time_utc = fields.Datetime.now()
                start_time = open_line.z_timesheet_start_date

                # Calculate final duration
                if start_time and end_time_utc:
                    duration = (end_time_utc - start_time).total_seconds() / 3600

                    # If there was accumulated time from pauses, add it
                    if hasattr(open_line, 'z_accumulated_time') and open_line.z_accumulated_time:
                        duration = open_line.z_accumulated_time

                    open_line.unit_amount = round(duration, 2)

                update_vals = {
                    'z_timesheet_end_date': end_time_utc,
                    'name': desc,
                }

                if hasattr(open_line, 'z_is_paused'):
                    update_vals['z_is_paused'] = False

                open_line.write(update_vals)

                # Handle file attachments
                attachment_ids = []
                if hasattr(request, 'httprequest') and request.httprequest.files:
                    files = request.httprequest.files
                    for file_key in files:
                        if file_key == 'attachments':
                            file_list = files.getlist(file_key)
                            for uploaded_file in file_list:
                                if uploaded_file and uploaded_file.filename:
                                    try:
                                        file_content = uploaded_file.read()
                                        attachment = request.env['ir.attachment'].sudo().create({
                                            'name': uploaded_file.filename,
                                            'type': 'binary',
                                            'datas': base64.b64encode(file_content),
                                            'res_model': 'account.analytic.line',
                                            'res_id': open_line.id,
                                            'mimetype': uploaded_file.content_type or 'application/octet-stream',
                                            'description': f'Timer attachment for timesheet {open_line.id}',
                                            'public': False,
                                        })
                                        attachment_ids.append(attachment.id)
                                    except Exception as e:
                                        _logger.error("Error uploading attachment: %s", str(e))

                if attachment_ids:
                    open_line.message_post(
                        body=f"Timer stopped with {len(attachment_ids)} attachment(s)",
                        attachment_ids=attachment_ids
                    )

                return Response(json.dumps({
                    'success': True,
                    'attachments_count': len(attachment_ids),
                    'timesheet_id': open_line.id,
                    'duration': round(duration, 2),
                    'action': 'stopped'
                }), content_type='application/json')

            else:
                return Response(json.dumps({'success': False, 'error': 'Invalid action'}),
                                content_type='application/json')

        except Exception as e:
            _logger.error('Timer error: %s', e)
            return Response(json.dumps({'success': False, 'error': str(e)}),
                            content_type='application/json')

    # Rest of the methods remain the same...
    @http.route('/portal/task/<int:task_id>/timesheet', type='http', auth='user', website=True, methods=['POST'])
    def portal_save_timesheet(self, task_id, **kw):
        try:
            task = request.env['project.task'].sudo().browse(task_id).exists()
            if not task:
                return Response(json.dumps({'error': 'Task not found'}), content_type='application/json')

            timesheet_id = int(kw.get('timesheet_id', 0))
            description = kw.get('description', '')
            hours = float(kw.get('hours', 0.0)) if kw.get('hours') else 0.0
            employee_id = int(kw.get('employee_id', 0)) if kw.get('employee_id') else False

            start_date = _parse_datetime_to_utc(kw.get('start_date'))
            end_date = _parse_datetime_to_utc(kw.get('end_date'))

            Line = request.env['account.analytic.line'].sudo()
            vals = {
                'task_id': task.id,
                'project_id': task.project_id.id if task.project_id else False,
                'name': description,
                'z_timesheet_start_date': start_date,
                'z_timesheet_end_date': end_date,
                'unit_amount': hours,
                'employee_id': employee_id,
                'date': fields.Date.context_today(request.env.user),
            }

            if timesheet_id:
                line = Line.browse(timesheet_id).exists()
                if line and line.task_id.id == task.id:
                    line.write(vals)
                else:
                    return Response(json.dumps({'error': 'Timesheet not found'}), content_type='application/json')
            else:
                Line.create(vals)

            return Response(json.dumps({'success': True}), content_type='application/json')

        except Exception as e:
            _logger.error("Error saving timesheet: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/timesheet/<int:timesheet_id>', type='http', auth='user', website=True)
    def portal_get_timesheet(self, task_id, timesheet_id):
        try:
            ts = request.env['account.analytic.line'].sudo().browse(timesheet_id).exists()
            if not ts or ts.task_id.id != task_id:
                return Response(json.dumps({'error': 'Timesheet not found'}), content_type='application/json')

            data = {
                'id': ts.id,
                'description': ts.name or '',
                'start_date': _format_datetime_to_user_tz(ts.z_timesheet_start_date),
                'end_date': _format_datetime_to_user_tz(ts.z_timesheet_end_date),
                'hours': ts.unit_amount,
                'employee_id': ts.employee_id.id if ts.employee_id else False,
                'employee_name': ts.employee_id.name if ts.employee_id else '',
            }
            return Response(json.dumps(data), content_type='application/json')

        except Exception as e:
            _logger.error("Error getting timesheet data: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/timesheet/delete/<int:timesheet_id>', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_delete_timesheet(self, task_id, timesheet_id, **kw):
        try:
            ts = request.env['account.analytic.line'].sudo().browse(timesheet_id).exists()
            if ts and ts.task_id.id == task_id:
                ts.unlink()
                return Response(json.dumps({'success': True}), content_type='application/json')
            return Response(json.dumps({'error': 'Timesheet not found'}), content_type='application/json')
        except Exception as e:
            _logger.error("Error deleting timesheet: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/subtask', type='http', auth='user', website=True, methods=['POST'])
    def portal_save_subtask(self, task_id, **post):
        try:
            task = request.env['project.task'].sudo().browse(task_id).exists()
            if not task:
                return Response(json.dumps({'success': False, 'error': 'Task not found'}),
                                content_type='application/json')

            subtask_id = post.get('subtask_id')
            head_ids = request.httprequest.form.getlist('z_head_assignes_ids')
            member_ids = request.httprequest.form.getlist('z_member_assignes_ids')

            vals = {
                'name': post.get('name') or 'New Subtask',
                'z_master_task_id': int(post.get('z_master_task_id')) if post.get('z_master_task_id') else False,
                'z_project_task_state': post.get('z_project_task_state', 'new'),
                'z_head_assignes_ids': [(6, 0, [int(x) for x in head_ids if x])],
                'z_member_assignes_ids': [(6, 0, [int(x) for x in member_ids if x])],
                'parent_id': task_id,
                'project_id': task.project_id.id if task.project_id else False,
                'partner_id': task.partner_id.id if task.partner_id else False,
            }

            if subtask_id:
                subtask = request.env['project.task'].sudo().browse(int(subtask_id)).exists()
                if subtask:
                    subtask.write(vals)
                else:
                    return Response(json.dumps({'success': False, 'error': 'Subtask not found'}),
                                    content_type='application/json')
            else:
                subtask = request.env['project.task'].sudo().create(vals)

            return Response(json.dumps({'success': True, 'id': subtask.id}),
                            content_type='application/json')

        except Exception as e:
            _logger.error("Error saving subtask: %s", str(e))
            return Response(json.dumps({'success': False, 'error': str(e)}),
                            content_type='application/json')

    @http.route('/portal/task/<int:task_id>/subtask/<int:subtask_id>', type='http', auth='user', website=True,
                methods=['GET'])
    def portal_get_subtask(self, task_id, subtask_id, **kw):
        try:
            subtask = request.env['project.task'].sudo().browse(subtask_id).exists()
            if not subtask:
                return Response(json.dumps({'error': 'Subtask not found'}), content_type='application/json')

            data = {
                'id': subtask.id,
                'name': subtask.name,
                'z_master_task_id': subtask.z_master_task_id.id if subtask.z_master_task_id else False,
                'z_project_task_state': subtask.z_project_task_state,
                'z_head_assignes_ids': subtask.z_head_assignes_ids.ids,
                'z_member_assignes_ids': subtask.z_member_assignes_ids.ids,
            }
            return Response(json.dumps(data), content_type='application/json')

        except Exception as e:
            _logger.error("Error getting subtask data: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/subtask/delete/<int:subtask_id>', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_delete_subtask(self, task_id, subtask_id, **kw):
        try:
            subtask = request.env['project.task'].sudo().browse(subtask_id).exists()
            if subtask and subtask.parent_id.id == task_id:
                subtask.unlink()
                return Response(json.dumps({'success': True}), content_type='application/json')
            return Response(json.dumps({'error': 'Subtask not found'}), content_type='application/json')
        except Exception as e:
            _logger.error("Error deleting subtask: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/invoice-plan', type='http', auth='user', website=True, methods=['POST'])
    def portal_save_invoice_plan(self, task_id, **kw):
        try:
            task = request.env['project.task'].sudo().browse(task_id).exists()
            if not task:
                return Response(json.dumps({'error': 'Task not found'}), content_type='application/json')

            invoice_plan_id = int(kw.get('invoice_plan_id', 0))

            def safe_float(val):
                try:
                    return float(val) if val and str(val).strip() else 0.0
                except (ValueError, TypeError):
                    return 0.0

            vals = {
                'z_invoce_plan_id': task.id,
                'z_name': kw.get('z_name', ''),
                'z_number_of_invoice': kw.get('z_number_of_invoice', ''),
                'z_invoice_date': kw.get('z_invoice_date') or False,
                'z_amount_total': safe_float(kw.get('z_amount_total')),
                'z_state': kw.get('z_state', 'draft'),
            }

            InvoicePlan = request.env['project.task.invoice.plan'].sudo()
            if invoice_plan_id:
                invoice_plan = InvoicePlan.browse(invoice_plan_id).exists()
                if invoice_plan and invoice_plan.z_invoce_plan_id.id == task.id:
                    invoice_plan.write(vals)
                else:
                    return Response(json.dumps({'error': 'Invoice plan not found'}), content_type='application/json')
            else:
                InvoicePlan.create(vals)

            return Response(json.dumps({'success': True}), content_type='application/json')

        except Exception as e:
            _logger.error("Error saving invoice plan: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/invoice-plan/<int:invoice_plan_id>', type='http', auth='user', website=True)
    def portal_get_invoice_plan(self, task_id, invoice_plan_id):
        try:
            invoice_plan = request.env['project.task.invoice.plan'].sudo().browse(invoice_plan_id).exists()
            if not invoice_plan or invoice_plan.z_invoce_plan_id.id != task_id:
                return Response(json.dumps({'error': 'Invoice plan not found'}), content_type='application/json')

            data = {
                'id': invoice_plan.id,
                'z_name': invoice_plan.z_name or '',
                'z_number_of_invoice': invoice_plan.z_number_of_invoice or '',
                'z_invoice_date': invoice_plan.z_invoice_date.strftime(
                    '%Y-%m-%d') if invoice_plan.z_invoice_date else '',
                'z_amount_total': round(invoice_plan.z_amount_total, 2),
                'z_state': invoice_plan.z_state or 'draft',
            }
            return Response(json.dumps(data), content_type='application/json')

        except Exception as e:
            _logger.error("Error getting invoice plan data: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')

    @http.route('/portal/task/<int:task_id>/invoice-plan/delete/<int:invoice_plan_id>', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_delete_invoice_plan(self, task_id, invoice_plan_id, **kw):
        try:
            invoice_plan = request.env['project.task.invoice.plan'].sudo().browse(invoice_plan_id).exists()
            if invoice_plan and invoice_plan.z_invoce_plan_id.id == task_id:
                invoice_plan.unlink()
                return Response(json.dumps({'success': True}), content_type='application/json')
            return Response(json.dumps({'error': 'Invoice plan not found'}), content_type='application/json')
        except Exception as e:
            _logger.error("Error deleting invoice plan: %s", str(e))
            return Response(json.dumps({'error': str(e)}), content_type='application/json')
