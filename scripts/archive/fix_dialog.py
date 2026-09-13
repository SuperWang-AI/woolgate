"""
修复后的对话框函数
直接替换到 admin.py 中
"""

def show_account_dialog_fixed(account_id: Optional[int] = None):
    """显示账号编辑对话框 - 修复版"""
    from nicegui import ui, app as nicegui_app
    
    # 创建一个延迟执行的函数
    async def show():
        account = None
        if account_id:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ModelAccount).where(ModelAccount.id == account_id)
                )
                account = result.scalar_one_or_none()
                if not account:
                    ui.notify('账号不存在', type='negative')
                    return
        
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label('编辑账号' if account else '新增账号').classes('text-xl font-bold mb-4')
            
            vendor = ui.input('厂商名称', value=account.vendor if account else '').classes('w-full')
            model_name = ui.input('模型ID', value=account.model_name if account else '').classes('w-full')
            api_key = ui.input('API Key', password=True, password_toggle_button=True, 
                             value='********' if account else '').classes('w-full')
            if account:
                ui.label('提示：不修改API Key时保持默认值即可').classes('text-xs text-gray-500')
            
            base_url = ui.input('接口地址（可选）', value=account.base_url if account and account.base_url else '').classes('w-full')
            priority = ui.number('优先级', value=account.priority if account else 50, min=0, max=100).classes('w-full')
            
            ui.separator()
            
            is_enable = ui.checkbox('启用账号', value=account.is_enable if account else True)
            quota_type = ui.select(['daily', 'once'], label='额度类型', 
                                  value=account.quota_type if account else 'daily').classes('w-full')
            quota_unit = ui.select(['token', 'currency'], label='配额单位', 
                                  value=account.quota_unit if account else 'token').classes('w-full')
            
            free_total_token = ui.number('免费Token总额', 
                                        value=account.free_total_token if account else 1000000, 
                                        min=0).classes('w-full')
            market_input_price = ui.number('市场输入单价(元/1M)', 
                                          value=account.market_input_price if account else 0.0, 
                                          step=0.1).classes('w-full')
            market_output_price = ui.number('市场输出单价(元/1M)', 
                                           value=account.market_output_price if account else 0.0, 
                                           step=0.1).classes('w-full')
            
            async def save_account():
                if not vendor.value or not model_name.value:
                    ui.notify('请填写必填字段', type='warning')
                    return
                
                account_data = {
                    'vendor': vendor.value,
                    'model_name': model_name.value,
                    'base_url': base_url.value or None,
                    'priority': int(priority.value),
                    'is_enable': is_enable.value,
                    'quota_type': quota_type.value,
                    'quota_unit': quota_unit.value,
                    'free_total_token': int(free_total_token.value),
                    'market_input_price': float(market_input_price.value),
                    'market_output_price': float(market_output_price.value),
                }
                
                # 处理API Key
                if not account or (api_key.value and api_key.value != '********'):
                    if not api_key.value:
                        ui.notify('请填写API Key', type='warning')
                        return
                    encrypted_key = encryption_service.encrypt(api_key.value)
                    account_data['api_key_encrypted'] = encrypted_key
                
                await create_or_update_account(account_data, account_id)
                action_text = '更新' if account else '创建'
                ui.notify(f"账号{action_text}成功！", type='positive')
                dialog.close()
                # 刷新页面
                ui.navigate.to('/accounts')
            
            with ui.row().classes('mt-4'):
                ui.button('保存', on_click=save_account).props('color=primary')
                ui.button('取消', on_click=dialog.close)
        
        dialog.open()
    
    # 使用 ui.timer 立即执行异步函数
    ui.timer(0.01, show, once=True)
