from aiogram import Router

from . import admin, common, happ, profiles, stats

router = Router(name="root")
# admin первым: FSM рассылки/добавления не перехватывается кнопками списка
router.include_router(admin.router)
router.include_router(common.router)
router.include_router(profiles.router)
router.include_router(happ.router)
router.include_router(stats.router)
