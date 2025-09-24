from odoo.addons.portal.controllers.portal import CustomerPortal, pager, get_error
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo import http, tools, _, SUPERUSER_ID
from odoo.http import request, Response
from html import unescape
from urllib.parse import urlencode
import logging
import math
import re

_logger = logging.getLogger(__name__)


class PortalProjectControllers(http.Controller):

    @http.route([
        '/portal/projects',
        '/portal/projects/<int:project_id>',
        '/portal/projects/page/<int:page>',
        '/portal/projects/delete/<int:project_id>',
        '/portal/projects/<int:project_id>/teams/delete/<int:employee_id>',
        '/portal/projects/<int:project_id>/program/delete/<int:program_id>',
    ], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_projects(self, page=1, project_id=None, employee_id=None, program_id=None, model=None, tab=None, function=None, deleted=None, view_type=None, search='', sortby='terbaru', groupby='', **kw):
        step = 3
        group_step = 3
        domain = []
        data_gantt = []
        url = '/portal/projects'
        if not project_id:
            project_id = kw.get('project_id')
        if not deleted:
            deleted = kw.get('deleted')
        if not function:
            function = kw.get('function')
        projects_status = False
        projects_description = False
        partner_ids = request.env['res.partner'].sudo().search([('is_company','=',True)], order='id asc')
        employees_ids = request.env['hr.employee'].sudo().search([], order='id asc')
        tag_ids = request.env['project.tags'].sudo().search([], order='id asc')

        # ===================== SORT & GROUP CONFIG =====================
        searchbar_sort = {
            'terbaru': {'label': 'Terbaru', 'order': 'id desc'},
            'terlama': {'label': 'Terlama', 'order': 'id asc'},
            'name': {'label': 'Project Name', 'order': 'label_tasks asc'},
            'sequence': {'label': 'Project Code', 'order': 'name asc'},
            'customer': {'label': 'Customer', 'order': 'partner_id desc'},
        }
        searchbar_group = {
            '': {'label': 'None'},
            'partner_id': {'label': 'Customer'},
            'z_project_manager_ids': {'label': 'Project Manager'},
            'z_project_teams_ids': {'label': 'Project Teams'},
        }
        view_type_settings = {
            'list': {'label': 'List'},
            # 'gantt': {'label': 'Gantt'}
        }
        sort_field = searchbar_sort[sortby]['order'] if sortby in searchbar_sort else 'id desc'
        if search:
            domain += [
                '|', '|',
                ('name', 'ilike', search),
                ('partner_id.name', 'ilike', search),
                ('user_id.name', 'ilike', search)
            ]

        # ===================== METHOD POST =====================
        if request.httprequest.method == 'POST':
            data_text_api = request.httprequest.form
            data_dict = data_text_api.to_dict(flat=False)
            keys_to_remove = [
                'csrf_token',
                'project_id',
                'function',
            ]
            if not model:
                if 'deleted' in data_dict:
                    data_dict.pop('deleted')
                ir_model_field_ids = request.env['ir.model.fields'].sudo().search([('model_id.model','=','project.project'),('ttype','=','many2many')], order='id desc')
                for field_id in ir_model_field_ids:
                    if field_id.name not in data_dict:
                        data_dict[field_id.name] = []
            for key in keys_to_remove:
                data_dict.pop(key, None)
            for key, value in data_dict.items():
                if value and len(value) == 1 and not '_ids' in key:
                    value = value[0]
                if value and '_id' in key and not '_ids' in key:
                    value = int(value)
                elif value and '_ids' in key:
                    data_array = []
                    if len(value) == 1 and value[0]:
                        data_array.append(int(value[0]))
                    elif len(value) > 1:
                        data_array = [int(v) for v in value if v]
                    value = [(6, 0, data_array)]
                elif value and 'date' in key and type(key) == 'datetime':
                    value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                elif value and 'date' in key and type(key) == 'date':
                    value = datetime.strptime(value, '%Y-%m-%d').date()
                if not value and type(key) == 'list':
                    value = [(6, 0, [])]
                elif not value and not type(key) == 'list':
                    value = False
                data_dict[key] = value
            if not model and 'description' in data_dict and data_dict['description']:
                data_dict['description'] = data_dict['description'].replace("\n", "<br/>")
            if model and model == 'project.project.program.name':
                if deleted:
                    project_ids = request.env['project.project.program.name'].sudo().search([('id','=',program_id)])
                    project_ids.unlink()
                    return request.make_json_response({'success': True})
                else:
                    project_ids = request.env['project.project.program.name'].create({
                        'z_project_id': project_id,
                        'z_name': data_dict['z_name'],
                    })
                    return request.make_json_response({
                        'success': True,
                        'project_id': project_id,
                        'program_id': project_ids.id,
                        'program_name': project_ids.z_name,
                        'updated_by': project_ids.write_uid.name or '',
                        'updated_date': project_ids.write_date.strftime('%Y-%m-%d') if project_ids.write_date else ''
                    })
            elif project_id and not model:
                if deleted and project_id and employee_id:
                    project_ids = request.env['project.project'].sudo().search([('id','=',project_id)])
                    project_ids.write({
                        'z_project_teams_ids': [(3, employee_id)]
                    })
                    employee_ids = request.env['hr.employee'].sudo().browse(employee_id)
                    return request.make_json_response({
                        'success': True,
                        'employee_id': employee_ids.id,
                        'name': employee_ids.name,
                        'job_position': employee_ids.job_id.name,
                    })
                elif deleted and project_id and not employee_id:
                    request.env['project.project'].sudo().browse(project_id).unlink()
                    return request.redirect(f'/portal/projects')
                elif not deleted and project_id and not employee_id:
                    project_ids = request.env['project.project'].sudo().search([('id','=',project_id)])
                    if function and function == 'confirm':
                        project_ids.action_confirm()
                    elif function and function == 'failed':
                        project_ids.action_failed()
                    elif function and function == 'set_to_draft':
                        project_ids.action_set_to_draft()
                    else:
                        project_ids.write(data_dict)
                    return request.redirect(f'/portal/projects/{project_ids.id}?view_type=form')
            elif not project_id and not model:

                project_ids = request.env['project.project'].sudo().create(data_dict)
                return request.redirect(f'/portal/projects/{project_ids.id}?view_type=form')

        # ===================== CONTENT =====================
        if project_id:
            domain += [('id','=',project_id)]
        total_projects = request.env['project.project'].sudo().search_count(domain)
        pager_details = pager(url=url, total=total_projects, page=page, step=step, scope=3, url_args={'search': search, 'sortby': sortby, 'groupby': groupby, 'view_type': view_type})
        projects = request.env['project.project'].sudo().search(domain, offset=pager_details['offset'], limit=step, order=sort_field)
        if view_type == 'form' and project_id:
            projects = request.env['project.project'].sudo().search(domain, limit=1)
            projects._portal_ensure_token()
            projects_status = projects._fields['z_project_status'].convert_to_export(projects.z_project_status, projects)
            desc = projects.description or ""
            desc = re.sub(r'<br\s*/?>', '\n', desc)
            desc = re.sub(r'</p>', '\n', desc)
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = unescape(desc)
            projects_description = "\n".join([line.strip() for line in desc.splitlines()]).strip()
        elif view_type == 'form' and not project_id:
            projects = []
        # ===================== GROUP BY + PAGINATION =====================
        if groupby:
            group_field_name = groupby
            read_groups = request.env['project.project'].sudo().read_group(
                domain,
                fields=[group_field_name],
                groupby=[group_field_name],
                orderby=group_field_name,
                limit=None
            )
            group_keys = [g[group_field_name][0] if g[group_field_name] else False for g in read_groups]
            url_args = dict(kw or {})
            for k in list(url_args.keys()):
                if k.startswith("group_page_"):
                    url_args.pop(k)
            url_args.update({
                'search': search,
                'sortby': sortby,
                'groupby': groupby,
            })
            common_query = urlencode(url_args, doseq=True)
            data_project_on_group = []
            Project = request.env['project.project'].sudo()
            field_obj = Project._fields.get(group_field_name)
            for idx, key in enumerate(group_keys):
                group_domain = list(domain)
                if key:
                    group_domain.append((group_field_name, '=', key))
                else:
                    group_domain.append((group_field_name, '=', False))
                projects_all = Project.search(group_domain, order=sort_field)
                page_param = f'group_page_{idx}'
                try:
                    page_for_group = int(request.httprequest.args.get(page_param, 1))
                    if page_for_group < 1:
                        page_for_group = 1
                except Exception:
                    page_for_group = 1
                offset = (page_for_group - 1) * group_step
                projects_paged = projects_all[offset: offset + group_step]
                total_items = len(projects_all)
                total_pages = (total_items + group_step - 1) // group_step
                pages = list(range(1, total_pages + 1))
                if field_obj and getattr(field_obj, 'comodel_name', None):
                    group_value = request.env[field_obj.comodel_name].sudo().browse(key) if key else 'Undefined'
                else:
                    group_value = key or 'Undefined'
                pager_group = {
                    'page_param': page_param,
                    'page': page_for_group,
                    'step': group_step,
                    'offset': offset,
                    'total': total_items,
                    'pages': pages,
                }
                data_project_on_group.append({
                    'group_value': group_value,
                    'projects': projects_paged,
                    'pager': pager_group,
                    'group_index': idx,
                })
            projects = data_project_on_group
        else:
            common_query = urlencode({'search': search, 'sortby': sortby, 'groupby': groupby}, doseq=True)
        # ===================== GANTT =====================
        if view_type and view_type == 'gantt':
            for x in projects:
                data_gantt.append({
                    "id": x.id,
                    "startTime": str(x.date_start) if x.date_start else "",
                    "endTime": str(x.date) if x.date else "",
                    "actualStartTime": str(x.z_actual_start_date) if x.z_actual_start_date else "",
                    "actualEndTime": str(x.z_actual_end_date) if x.z_actual_end_date else "",
                    "name": x.name or "",
                    "progress": x.z_progress_project or 0,
                })
        values = {
            # filter
            'page_name': 'Projects',
            'search': search,
            'sortby': sortby,
            'groupby': groupby,
            'searchbar_sort': searchbar_sort,
            'searchbar_group': searchbar_group,
            'pager_header': pager_details,
            'common_query': common_query,
            # view
            'view_type': view_type,
            'view_type_settings': view_type_settings,
            # data
            'projects': projects,
            'projects_status': projects_status,
            'projects_description': projects_description,
            'partner_ids': partner_ids,
            'employees_ids': employees_ids,
            'tag_ids': tag_ids,
            'data_gantt': data_gantt,
            'kw': kw,
        }
        return request.render('z_project.portal_project', values)


