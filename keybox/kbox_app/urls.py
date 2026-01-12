from django.urls import path
from . import views
from . import views_management
from . import views_api

urlpatterns = [
    # ==================== AUTHENTICATION ====================
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    
    # ==================== DASHBOARD ====================
    path('', views.dashboard, name='dashboard'),

    # ==================== ADMIN PAGES ====================
    path('rfid/register/', views.rfid_register, name='rfid_register'),
    path('reports/', views.reports, name='reports'),
    path('transaction-logs/', views.transaction_logs, name='transaction_logs'),

    # ==================== Denied Access Logs (separate page) ==================
    path('denied-access-logs/', views.denied_access_logs, name='denied_access_logs'),

    # ==================== API FOR RFID/ARDUINO ====================
    path('api/rfid-swipe/', views.rfid_swipe, name='rfid_swipe'),
    path('api/manual-trigger/', views.manual_trigger_api, name='manual_trigger_api'),
    
    # ⭐ ESP32 Heartbeat API - ESP32 devices call this
    path('api/esp32/heartbeat/', views.esp32_heartbeat, name='esp32_heartbeat'),
    
    # ==================== ROOM MANAGEMENT ====================
    path('rooms/', views_management.room_list, name='room_list'),
    path('rooms/add/', views_management.room_add, name='room_add'),
    path('rooms/<int:room_id>/edit/', views_management.room_edit, name='room_edit'),
    path('rooms/<int:room_id>/toggle/', views_management.room_toggle_status, name='room_toggle_status'),
    
    # ==================== SCHEDULE MANAGEMENT ====================
    path('schedules/', views_management.schedule_list, name='schedule_list'),
    path('schedules/add/', views_management.schedule_add, name='schedule_add'),
    path('schedules/<int:schedule_id>/edit/', views_management.schedule_edit, name='schedule_edit'),
    path('schedules/<int:schedule_id>/toggle/', views_management.schedule_toggle_status, name='schedule_toggle_status'),
    path('schedules/<int:schedule_id>/delete/', views_management.schedule_delete, name='schedule_delete'),
    
    # ==================== FACULTY MANAGEMENT ====================
    path('faculty/', views_management.faculty_list, name='faculty_list'),
    path('faculty/add/', views_management.faculty_add, name='faculty_add'),
    path('faculty/<int:faculty_id>/edit/', views_management.faculty_edit, name='faculty_edit'),
    path('faculty/<int:faculty_id>/toggle/', views_management.faculty_toggle_status, name='faculty_toggle_status'),
    path('faculty/<int:faculty_id>/access/', views_management.faculty_manage_access, name='faculty_manage_access'),

    # ==================== MANUAL DOOR CONTROL ====================
    path('manual-control/', views_management.manual_door_control, name='manual_door_control'),
    path('manual-control/trigger/', views_management.manual_door_trigger, name='manual_door_trigger'),
    path('manual-door-log-delete/', views_management.manual_door_log_delete, name='manual_door_log_delete'),
    
    # ==================== ESP32 DEVICE MANAGEMENT ====================
    path('esp32/', views_management.esp32_list, name='esp32_list'),
    path('esp32/add/', views_management.esp32_add, name='esp32_add'),
    path('esp32/<int:device_id>/edit/', views_management.esp32_edit, name='esp32_edit'),
    path('esp32/<int:device_id>/toggle/', views_management.esp32_toggle_status, name='esp32_toggle_status'),
    path('esp32/<int:device_id>/delete/', views_management.esp32_delete, name='esp32_delete'),
    
    # ⭐ ESP32 Status API - Sidebar polls this for real-time status
    path('api/esp32/status/', views_management.esp32_status_api, name='esp32_status_api'),
    path('esp32/<int:device_id>/schedules/', views_management.esp32_device_schedules, name='esp32_device_schedules'),

    # API log-offline
    path('api/esp32/schedules/', views_api.esp32_get_schedules, name='esp32_get_schedules'),
    path('api/esp32/check-updates/', views_api.esp32_check_updates, name='esp32_check_updates'),
    path('api/esp32/log-offline/', views_api.esp32_log_offline_access, name='esp32_log_offline_access'),
]