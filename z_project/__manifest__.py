{
    "name": "[Custom] Project",
    "summary": "Responsive web client, community-supported",
    "description": "This module contains all the common features of Project.",
    "version": "1.0.0",
    'category': 'Base',
    "license": "LGPL-3",
    "depends": ["web","base","project","mail","portal","hr","hr_timesheet"],
    "data": [
        # security
        'security/ir.model.access.csv',
        'security/res_groups.xml',

        # views
        'views/res_users.xml',
        'views/correction_timesheet.xml',
        'views/task_master.xml',
        'views/severity_master.xml',
        'views/technology_used.xml',
        'views/area_regional.xml',
        'views/project_project.xml',
        'views/project_task.xml',
        'report/views/portal_project.xml',
        'report/views/portal_tasks.xml',
        # default portal
        'report/views/portal_dashboard.xml',
        'report/views/portal_security.xml',
        'report/views/portal_layout.xml',

        # data
        'data/ir_sequence.xml',
        'data/ir_ui_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'z_project/static/src/js/realtime_datetime.js',
            'z_project/static/src/xml/realtime_datetime.xml',
        ],
        'web.assets_frontend': [
            'z_project/static/src/js/project_project.js',
        ],

    },
    'sequence': 1,
    'installable': True,
    'auto_install': False,
    'application': True,
    'bootstrap': True,
}
