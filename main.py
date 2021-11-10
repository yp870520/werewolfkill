import asyncio
import sys
from logging import getLogger, basicConfig

from pywebio import start_server
from pywebio.input import *
from pywebio.output import *
from pywebio.session import defer_call, get_current_task_id

from enums import WitchRule, GuardRule, Role, GameStage, PlayerStatus
from models.room import Room
from models.user import User
from utils import add_cancel_button

basicConfig(stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = getLogger('Wolf')
logger.setLevel('DEBUG')


async def main():
    """六味地黄丸专用狼人杀"""
    put_markdown("## 狼人杀法官")

    current_user = User.alloc(
        await input('请输入你的昵称',
                    required=True,
                    validate=User.validate_nick,
                    help_text='请使用一个易于分辨的名称'),
        get_current_task_id()
    )

    @defer_call
    def on_close():
        User.free(current_user)

    put_text(f'你好，{current_user.nick}')
    data = await input_group(
        '大厅', inputs=[actions(name='cmd', buttons=['创建房间', '加入房间'])]
    )

    if data['cmd'] == '创建房间':
        room_config = await input_group('房间设置', inputs=[
            input(name='wolf_num', label='普通狼数', type=NUMBER, value='3'),
            checkbox(name='god_wolf', label='特殊狼', inline=True, options=Role.as_god_wolf_options()),
            input(name='citizen_num', label='普通村民数', type=NUMBER, value='4'),
            checkbox(name='god_citizen', label='特殊村民', inline=True, options=Role.as_god_citizen_options()),
            select(name='witch_rule', label='女巫解药规则', options=WitchRule.as_options()),
            select(name='guard_rule', label='守卫规则', options=GuardRule.as_options()),
        ])
        room = Room.alloc(room_config)
    elif data['cmd'] == '加入房间':
        room = Room.get(await input('房间号', type=TEXT, validate=Room.validate_room_join))
    else:
        raise NotImplementedError

    put_scrollable(current_user.game_msg, height=200, keep_bottom=True)
    current_user.game_msg.append(put_text(room.desc()))

    room.add_player(current_user)

    while True:
        await asyncio.sleep(0.2)
        # 非夜晚房主操作
        host_ops = []
        if current_user is room.get_host():
            if not room.started:
                host_ops = [
                    actions(name='host_op', buttons=['开始游戏'], help_text='你是房主')
                ]
            elif room.stage == GameStage.Day and room.round > 0:
                dead_users_list = [user for user in room.list_dead_players()]
                for d_user in dead_users_list:
                    if d_user.role == Role.HUNTER and room.hunter_killed:
                        host_ops = [
                            actions(
                                name='host_vote_op_with_hunt_day',
                                buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                                help_text='你是房主，选择猎人带走的玩家'
                            )                       
                        ]
                        room.hunter_killed = False
                host_ops.append(
                    actions(
                        name='host_vote_op',
                        buttons=[user.nick for user in room.list_alive_players()],
                        help_text='你是房主，本轮需要选择出局玩家'
                    )                    
                )
        # 玩家操作
        user_ops = []
        if room.started:
            if room.stage == GameStage.WOLF and current_user.should_act():
                user_ops = [
                    actions(
                        name='wolf_team_op',
                        buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                        help_text='狼人阵营，请选择要击杀的对象。'
                    )
                ]
                current_user.send_msg(f'狼人阵营为 {room.list_wolf_players()}')
            if room.stage == GameStage.DETECTIVE and current_user.should_act():
                user_ops = [
                    actions(
                        name='detective_team_op',
                        buttons=[user.nick for user in room.list_alive_players()],
                        help_text='预言家，请选择要查验的对象。'
                    )
                ]
            if room.stage == GameStage.WITCH and current_user.should_act():
                if current_user.witch_has_heal() and current_user.witch_has_poison():
                    current_user.send_msg(f'昨晚被杀的是 {room.list_pending_kill_players()}')
                    user_ops = [
                        radio(name='witch_mode', options=['解药', '毒药'], required=True, inline=True),
                        actions(
                            name='witch_team_op',
                            buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                            help_text='女巫，请选择你的操作。'
                        )
                    ]
                elif not current_user.witch_has_heal() and current_user.witch_has_poison():
                    current_user.send_msg('你已经没有解药了')
                    user_ops = [
                        radio(name='witch_mode', options=['毒药'], required=True, inline=True),
                        actions(
                            name='witch_team_op',
                            buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                            help_text='女巫，请选择你的操作。'
                        )
                    ]                    
                else:
                    current_user.witch_no_do()


            if room.stage == GameStage.GUARD and current_user.should_act():
                user_ops = [
                    actions(
                        name='guard_team_op',
                        buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                        help_text='守卫，请选择你的操作。'
                    )
                ]
            if room.stage == GameStage.HUNTER and current_user.should_act() and not room.hunter_vote:  
                current_user.hunter_gun_status()

            if room.stage == GameStage.HUNTER and not current_user.should_act() and current_user.role == Role.HUNTER:
                current_user.send_msg('猎人已经开枪，无需操作')
                room.waiting = False
                room.enter_null_stage()

            if room.stage == GameStage.HUNTER_SHOOT and current_user.should_act():
                user_ops = [
                    actions(
                        name='host_vote_op_with_hunt',
                        buttons=add_cancel_button([user.nick for user in room.list_alive_players()]),
                        help_text='选择你要开枪带走的玩家'
                    )                       
                ]               

        ops = host_ops + user_ops
        if not ops:
            continue

        # UI
        if host_ops + user_ops:
            current_user.input_blocking = True
        data = await input_group('操作', inputs=host_ops + user_ops, cancelable=True)
        current_user.input_blocking = False

        # Canceled
        if data is None:
            current_user.skip()
            continue

        # Host logic
        if data.get('host_op') == '开始游戏':
            await room.start_game()
        if data.get('host_vote_op'):
            await room.vote_kill(data.get('host_vote_op'))
        if data.get('host_vote_op_with_hunt_day'):
            await room.hunt_day_kill(data.get('host_vote_op_with_hunt_day'))              
        if data.get('host_vote_op_with_hunt'):
            # await room.hunt_kill(data.get('host_vote_op_with_hunt'))
            current_user.hunt_kill(data.get('host_vote_op_with_hunt'))            
        # Wolf logic
        if data.get('wolf_team_op'):
            current_user.wolf_kill_player(nick=data.get('wolf_team_op'))
        # Detective logic
        if data.get('detective_team_op'):
            current_user.detective_identify_player(nick=data.get('detective_team_op'))
        # Witch logic
        if data.get('witch_team_op'):
            if data.get('witch_mode') == '解药':
                current_user.witch_heal_player(nick=data.get('witch_team_op'))
            elif data.get('witch_mode') == '毒药':
                current_user.witch_kill_player(nick=data.get('witch_team_op'))
        # Guard logic
        if data.get('guard_team_op'):
            current_user.guard_protect_player(nick=data.get('guard_team_op'))


if __name__ == '__main__':
    start_server(main, debug=False, host='0.0.0.0', port=80, cdn=False)
