import pygame

class Button():
    def __init__(self, pos = (0,0), width = 473, height = 177, image = None, scale = 1, num = 0):
        self.x = pos[0]
        self.y = pos[1]
        self.width = image.get_width()*scale
        self.height = image.get_height()*scale
        self.image = pygame.transform.scale(image, (self.width ,self.height))
        self.rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.clicked = False
        self.num = num

    def draw(self, screen):
        # 绘制按钮
        screen.blit(self.image, self.rect)

    def update(self, mouse_pos):
        # 检查鼠标位置是否在按钮上
        if self.rect.collidepoint(mouse_pos):
            self.clicked = True
        else:
            self.clicked = False
        return self.num