from aiogram import Router

from . import common, profiles, stats

router = Router(name="root")
router.include_router(common.router)
router.include_router(profiles.router)
router.include_router(stats.router)
