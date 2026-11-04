from django.urls import path,re_path
from drf_spectacular.views import SpectacularJSONAPIView
from portal.permissions import AdminAccess
from portal import views as v,auth_views as a,file_views as f

urlpatterns=[
    path('api/v1/auth/csrf',a.CsrfView.as_view()),path('api/v1/auth/login',a.LoginView.as_view()),path('api/v1/auth/logout',a.LogoutView.as_view()),
    path('api/v1/me',a.MeView.as_view()),path('api/v1/me/change-password',a.PasswordView.as_view()),path('api/v1/me/mfa/start',a.MFAStartView.as_view()),path('api/v1/me/mfa/verify',a.MFAVerifyView.as_view()),
    path('api/v1/me/contact',v.SelfContactView.as_view()),path('api/v1/me/location',v.SelfLocationView.as_view()),path('api/v1/me/profile',v.SelfProfileView.as_view()),
    path('api/v1/employees',v.EmployeesView.as_view()),path('api/v1/employees/duplicates',v.EmployeeDuplicatesView.as_view()),path('api/v1/employees/export',v.ExportView.as_view()),
    path('api/v1/employees/import/preview',v.ImportPreviewView.as_view()),path('api/v1/employees/import/<uuid:id>/commit',v.ImportCommitView.as_view()),
    path('api/v1/employees/<uuid:id>',v.EmployeeView.as_view()),path('api/v1/employees/<uuid:id>/archive',v.EmployeeArchiveView.as_view()),path('api/v1/employees/<uuid:id>/restore',v.EmployeeRestoreView.as_view()),path('api/v1/employees/<uuid:id>/history',v.HistoryView.as_view()),
    path('api/v1/org-units',v.UnitsView.as_view()),path('api/v1/org-units/<uuid:id>',v.UnitView.as_view()),path('api/v1/offices',v.OfficesView.as_view()),path('api/v1/offices/<uuid:id>',v.OfficeView.as_view()),
    path('api/v1/birthdays/upcoming',v.BirthdaysView.as_view()),path('api/v1/search',v.SearchView.as_view()),
    path('api/v1/news',v.NewsView.as_view()),path('api/v1/news/<uuid:id>',v.ArticleView.as_view()),path('api/v1/news/<uuid:id>/view',v.ArticleViewedView.as_view()),
    path('api/v1/documents',v.DocumentsView.as_view()),path('api/v1/documents/<uuid:id>',v.DocumentView.as_view()),path('api/v1/documents/<uuid:id>/versions',v.VersionsView.as_view()),
    path('api/v1/documents/<uuid:id>/versions/<uuid:version_id>',v.VersionView.as_view()),path('api/v1/documents/<uuid:id>/versions/<uuid:version_id>/reprocess',f.ReprocessView.as_view()),
    path('api/v1/files',f.UploadView.as_view()),path('api/v1/files/<uuid:id>/security-status',f.FileStateView.as_view()),path('api/v1/files/<uuid:id>/download',f.FileDownloadView.as_view()),
    path('api/v1/content/<str:kind>/<uuid:id>/trash',v.ContentTrashView.as_view()),path('api/v1/trash',v.TrashView.as_view()),path('api/v1/trash/<str:kind>/<uuid:id>',v.TrashItemView.as_view()),path('api/v1/trash/<str:kind>/<uuid:id>/restore',v.ContentRestoreView.as_view()),
    path('api/v1/admin/users',a.UsersView.as_view()),path('api/v1/admin/users/<int:id>',a.UserView.as_view()),path('api/v1/admin/users/<int:id>/reset-password',a.ResetPasswordView.as_view()),path('api/v1/admin/users/<int:id>/reset-mfa',a.ResetMFAView.as_view()),path('api/v1/admin/system',v.SystemView.as_view()),
    path('api/health/live',v.LiveView.as_view()),path('api/health/ready',v.ReadyView.as_view()),
    path('api/internal/worker/claim',f.WorkerClaimView.as_view()),path('api/internal/worker/heartbeat',f.WorkerHeartbeatView.as_view()),path('api/internal/worker/<uuid:id>/file',f.WorkerFileView.as_view()),path('api/internal/worker/<uuid:id>/result',f.WorkerResultView.as_view()),
    path('api/schema',SpectacularJSONAPIView.as_view(permission_classes=[AdminAccess]),name='schema'),
    path('api/docs',SpectacularJSONAPIView.as_view(permission_classes=[AdminAccess]),name='api-docs'),
    re_path(r'^api/(?P<path>.*)$',v.api_not_found),re_path(r'^(?P<path>.*)$',v.spa),
]
